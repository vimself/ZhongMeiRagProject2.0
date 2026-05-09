from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import require_admin
from app.db.session import get_db_session
from app.models.auth import AuditLog, User
from app.schemas.admin import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    AdminUserListResponse,
    AdminUserOut,
    AuditLogListResponse,
    AuditLogOut,
)
from app.security.password import hash_password

router = APIRouter(prefix="/api/v2/admin", tags=["admin"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AdminUser = Annotated[User, Depends(require_admin)]


def _avatar_url(avatar_path: str | None) -> str | None:
    if not avatar_path:
        return None
    return f"/uploads/avatars/{avatar_path}"


def _admin_user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        require_password_change=user.require_password_change,
        avatar_url=_avatar_url(user.avatar_path),
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
    )


def _audit_log_out(log: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=log.id,
        actor_user_id=log.actor_user_id,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        ip_address=log.ip_address,
        details=log.details or {},
        created_at=log.created_at.isoformat(),
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    admin: AdminUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=128),
    role: str = Query("", max_length=32),
    is_active: bool | None = Query(None),
) -> AdminUserListResponse:
    query = select(User)
    count_query = select(func.count()).select_from(User)

    if search:
        pattern = f"%{search}%"
        condition = User.username.ilike(pattern) | User.display_name.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)
    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
        count_query = count_query.where(User.is_active == is_active)

    total = (await db.execute(count_query)).scalar_one()
    offset = (page - 1) * page_size
    query = query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    users = list(result.scalars().all())

    return AdminUserListResponse(
        items=[_admin_user_out(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    body: AdminCreateUserRequest,
    admin: AdminUser,
    db: DbSession,
) -> AdminUserOut:
    username = body.username.strip().lower()
    existing = await db.scalar(select(User).where(User.username == username))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"用户名 '{username}' 已存在",
        )
    user = User(
        username=username,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.flush()
    await _record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.create",
        target_type="user",
        target_id=user.id,
        request=request,
        details={"username": username, "role": body.role},
    )
    await db.commit()
    await db.refresh(user)
    return _admin_user_out(user)


@router.put("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: str,
    request: Request,
    body: AdminUpdateUserRequest,
    admin: AdminUser,
    db: DbSession,
) -> AdminUserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # Prevent admin from demoting/deactivating themselves
    if user.id == admin.id:
        if body.role is not None and body.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能修改自己的管理员角色",
            )
        if body.is_active is not None and not body.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能停用自己的账号",
            )

    changes: dict[str, object] = {}
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
        changes["display_name"] = user.display_name
    if body.role is not None:
        user.role = body.role
        changes["role"] = user.role
    if body.is_active is not None:
        user.is_active = body.is_active
        changes["is_active"] = user.is_active
    if body.require_password_change is not None:
        user.require_password_change = body.require_password_change
        changes["require_password_change"] = user.require_password_change

    await _record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.update",
        target_type="user",
        target_id=user.id,
        request=request,
        details=changes,
    )
    await db.commit()
    await db.refresh(user)
    return _admin_user_out(user)


@router.post("/users/{user_id}/reset-password", response_model=AdminUserOut)
async def reset_password(
    user_id: str,
    request: Request,
    body: AdminResetPasswordRequest,
    admin: AdminUser,
    db: DbSession,
) -> AdminUserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    user.password_hash = hash_password(body.new_password)
    user.require_password_change = True
    await _record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.reset_password",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return _admin_user_out(user)


@router.delete("/users/{user_id}", response_model=AdminUserOut)
async def disable_user(
    user_id: str,
    request: Request,
    admin: AdminUser,
    db: DbSession,
) -> AdminUserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能停用自己的账号",
        )
    user.is_active = False
    await _record_audit(
        db,
        actor_user_id=admin.id,
        action="admin.user.disable",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return _admin_user_out(user)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    admin: AdminUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    target_type: str = Query("", max_length=64),
    target_id: str = Query("", max_length=128),
    action: str = Query("", max_length=64),
) -> AuditLogListResponse:
    query = select(AuditLog)
    count_query = select(func.count()).select_from(AuditLog)

    if target_type:
        query = query.where(AuditLog.target_type == target_type)
        count_query = count_query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
        count_query = count_query.where(AuditLog.target_id == target_id)
    if action:
        query = query.where(AuditLog.action.ilike(f"%{action}%"))
        count_query = count_query.where(AuditLog.action.ilike(f"%{action}%"))

    total = (await db.execute(count_query)).scalar_one()
    offset = (page - 1) * page_size
    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    logs = list(result.scalars().all())

    return AuditLogListResponse(
        items=[_audit_log_out(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )
