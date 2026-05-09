from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import current_user
from app.db.session import get_db_session
from app.models.auth import User
from app.schemas.user import ChangePasswordViaUserRequest, UpdateProfileRequest, UserProfileOut
from app.security.password import hash_password, verify_password

router = APIRouter(prefix="/api/v2/user", tags=["user"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(current_user)]

AVATAR_MAX_SIZE = 5 * 1024 * 1024  # 5 MB
AVATAR_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
AVATAR_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
UPLOAD_BASE = Path("uploads/avatars")


def _avatar_url(avatar_path: str | None) -> str | None:
    if not avatar_path:
        return None
    return f"/uploads/avatars/{avatar_path}"


def _user_profile_out(user: User) -> UserProfileOut:
    return UserProfileOut(
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


@router.get("/profile", response_model=UserProfileOut)
async def get_profile(user: CurrentUser) -> UserProfileOut:
    return _user_profile_out(user)


@router.put("/profile", response_model=UserProfileOut)
async def update_profile(
    request: Request,
    body: UpdateProfileRequest,
    user: CurrentUser,
    db: DbSession,
) -> UserProfileOut:
    managed = await db.get(User, user.id)
    if managed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    managed.display_name = body.display_name.strip()
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="user.update_profile",
        target_type="user",
        target_id=user.id,
        request=request,
        details={"display_name": managed.display_name},
    )
    await db.commit()
    await db.refresh(managed)
    return _user_profile_out(managed)


@router.post("/avatar", response_model=UserProfileOut)
async def upload_avatar(
    request: Request,
    file: UploadFile,
    user: CurrentUser,
    db: DbSession,
) -> UserProfileOut:
    if file.content_type not in AVATAR_ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {file.content_type}，"
            f"允许: {', '.join(sorted(AVATAR_ALLOWED_MIME))}",
        )
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in AVATAR_ALLOWED_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件扩展名: {ext}，允许: {', '.join(sorted(AVATAR_ALLOWED_EXT))}",
        )

    content = await file.read()
    if len(content) > AVATAR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件大小超过限制: {len(content)} bytes，最大允许 {AVATAR_MAX_SIZE} bytes",
        )

    managed = await db.get(User, user.id)
    if managed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # Remove old avatar file if exists
    if managed.avatar_path:
        old_file = UPLOAD_BASE / managed.avatar_path
        if old_file.is_file():
            old_file.unlink()

    # Sharded storage: uploads/avatars/{user_id}/{uuid}.{ext}
    shard_dir = UPLOAD_BASE / user.id
    shard_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = shard_dir / filename
    file_path.write_bytes(content)

    managed.avatar_path = f"{user.id}/{filename}"
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="user.upload_avatar",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    await db.commit()
    await db.refresh(managed)
    return _user_profile_out(managed)


@router.delete("/avatar", response_model=UserProfileOut)
async def delete_avatar(
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> UserProfileOut:
    managed = await db.get(User, user.id)
    if managed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if managed.avatar_path:
        file_path = UPLOAD_BASE / managed.avatar_path
        if file_path.is_file():
            file_path.unlink()
        managed.avatar_path = None
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="user.delete_avatar",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    await db.commit()
    await db.refresh(managed)
    return _user_profile_out(managed)


@router.post("/change-password")
async def change_password(
    request: Request,
    body: ChangePasswordViaUserRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, str]:
    managed = await db.get(User, user.id)
    if managed is None or not verify_password(body.old_password, managed.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    managed.password_hash = hash_password(body.new_password)
    managed.require_password_change = False
    await _record_audit(
        db,
        actor_user_id=user.id,
        action="user.change_password",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    await db.commit()
    return {"status": "ok"}
