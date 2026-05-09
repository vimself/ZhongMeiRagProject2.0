from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import get_settings
from app.db.session import get_db_session
from app.models.auth import AuditLog, AuthLoginAttempt, LoginRecord, User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserOut,
)
from app.security.jwt import create_access_token, create_refresh_token, decode_token
from app.security.login_limiter import login_failure_limiter
from app.security.password import hash_password, verify_password

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])
api_limiter = Limiter(key_func=get_remote_address)
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(current_user)]


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:512]


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        require_password_change=user.require_password_change,
    )


def _expires_in_seconds(expires_at: datetime) -> int:
    return max(0, int((expires_at - datetime.now(UTC)).total_seconds()))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _record_login_attempt(
    db: AsyncSession,
    *,
    subject: str,
    ip_address: str,
    success: bool,
    reason: str,
) -> None:
    db.add(
        AuthLoginAttempt(
            subject=subject.strip().lower(),
            ip_address=ip_address,
            success=success,
            reason=reason,
        )
    )
    await db.flush()


async def _record_audit(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    request: Request,
    details: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            details=details or {},
        )
    )
    await db.flush()


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    body: LoginRequest,
    db: DbSession,
) -> TokenResponse:
    ip_address = _client_ip(request)
    username = body.username.strip().lower()
    await login_failure_limiter.ensure_allowed(username, ip_address)

    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        await _record_login_attempt(
            db,
            subject=username,
            ip_address=ip_address,
            success=False,
            reason="invalid_credentials",
        )
        await db.commit()
        await login_failure_limiter.record_failure(username, ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    await login_failure_limiter.clear(username, ip_address)
    access_token = create_access_token(subject=user.id, role=user.role)
    refresh_token = create_refresh_token(subject=user.id)
    user.last_login_at = datetime.now(UTC)
    db.add(
        LoginRecord(
            user_id=user.id,
            refresh_token_jti=refresh_token.jti,
            ip_address=ip_address,
            user_agent=_user_agent(request),
            expires_at=refresh_token.expires_at,
        )
    )
    await _record_login_attempt(
        db,
        subject=username,
        ip_address=ip_address,
        success=True,
        reason="ok",
    )
    await db.commit()
    await db.refresh(user)
    return TokenResponse(
        access_token=access_token.token,
        refresh_token=refresh_token.token,
        expires_in=_expires_in_seconds(access_token.expires_at),
        user=_user_out(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: DbSession,
) -> TokenResponse:
    token_data = decode_token(body.refresh_token, expected_type="refresh")
    login_record = await db.scalar(
        select(LoginRecord).where(LoginRecord.refresh_token_jti == token_data.jti)
    )
    if (
        login_record is None
        or login_record.revoked_at is not None
        or _as_utc(login_record.expires_at) <= datetime.now(UTC)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌已失效")

    user = await db.get(User, token_data.subject)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")

    access_token = create_access_token(subject=user.id, role=user.role)
    return TokenResponse(
        access_token=access_token.token,
        refresh_token=body.refresh_token,
        expires_in=_expires_in_seconds(access_token.expires_at),
        user=_user_out(user),
    )


@router.post("/logout")
async def logout(
    request: Request,
    body: LogoutRequest,
    db: DbSession,
) -> dict[str, str]:
    token_data = decode_token(body.refresh_token, expected_type="refresh")
    login_record = await db.scalar(
        select(LoginRecord).where(LoginRecord.refresh_token_jti == token_data.jti)
    )
    if login_record is not None and login_record.revoked_at is None:
        login_record.revoked_at = datetime.now(UTC)
        await _record_audit(
            db,
            actor_user_id=login_record.user_id,
            action="auth.logout",
            target_type="user",
            target_id=login_record.user_id,
            request=request,
        )
        await db.commit()
    return {"status": "ok"}


@router.post("/change-password")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, str]:
    managed_user = await db.get(User, user.id)
    if managed_user is None or not verify_password(body.old_password, managed_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    managed_user.password_hash = hash_password(body.new_password)
    managed_user.require_password_change = False
    await _record_audit(
        db,
        actor_user_id=managed_user.id,
        action="auth.change_password",
        target_type="user",
        target_id=managed_user.id,
        request=request,
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.get("/config")
async def auth_config() -> dict[str, int]:
    settings = get_settings()
    return {
        "access_token_minutes": settings.jwt_access_token_minutes,
        "refresh_token_days": settings.jwt_refresh_token_days,
        "login_failed_limit": settings.login_failed_limit,
    }
