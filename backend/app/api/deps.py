from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.auth import User
from app.security.jwt import TokenData, decode_token

bearer = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
PdfToken = Annotated[str, Query(...)]


async def current_user(
    credentials: BearerCredentials,
    db: DbSession,
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = decode_token(credentials.credentials, expected_type="access")
    user = await db.get(User, token_data.subject)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    return user


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


@dataclass(frozen=True)
class PdfTokenUser:
    user: User
    token: TokenData
    document_id: str
    knowledge_base_id: str | None


async def pdf_token_user(
    token: PdfToken,
    db: DbSession,
) -> PdfTokenUser:
    token_data = decode_token(token, expected_type="pdf_preview")
    user = await db.get(User, token_data.subject)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已停用")
    document_id = token_data.claims.get("doc")
    knowledge_base_id = token_data.claims.get("kb")
    if not isinstance(document_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PDF token 缺少文档范围",
        )
    return PdfTokenUser(
        user=user,
        token=token_data,
        document_id=document_id,
        knowledge_base_id=knowledge_base_id if isinstance(knowledge_base_id, str) else None,
    )
