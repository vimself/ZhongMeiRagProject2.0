from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, current_user
from app.models.auth import User
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.services.deletion import DOCUMENT_DELETING_STATUS

VALID_ROLES = {"owner", "editor", "viewer"}


async def get_kb_or_404(
    kb_id: str,
    db: DbSession,
) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or not kb.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return kb


async def _get_user_kb_role(
    db: AsyncSession,
    user_id: str,
    kb_id: str,
) -> str | None:
    result = await db.execute(
        select(KnowledgeBasePermission.role).where(
            KnowledgeBasePermission.knowledge_base_id == kb_id,
            KnowledgeBasePermission.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _require_role(allowed: set[str]) -> Callable[..., Any]:
    """Return a dependency that checks the user has one of *allowed* roles (or is admin)."""

    async def _check(
        kb: Annotated[KnowledgeBase, Depends(get_kb_or_404)],
        user: Annotated[User, Depends(current_user)],
        db: DbSession,
    ) -> tuple[KnowledgeBase, str]:
        if user.role == "admin":
            return kb, "admin"
        role = await _get_user_kb_role(db, user.id, kb.id)
        if role is None or role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="没有访问此知识库的权限",
            )
        return kb, role

    return _check


# Concrete dependencies used by routes
require_viewer = _require_role({"viewer", "editor", "owner"})
require_editor = _require_role({"editor", "owner"})
require_owner = _require_role({"owner"})

RequireViewer = Annotated[tuple[KnowledgeBase, str], Depends(require_viewer)]
RequireEditor = Annotated[tuple[KnowledgeBase, str], Depends(require_editor)]
RequireOwner = Annotated[tuple[KnowledgeBase, str], Depends(require_owner)]


async def require_document_role(
    db: AsyncSession,
    user: User,
    document_id: str,
    allowed: set[str],
) -> tuple[Document, str]:
    document = await db.get(Document, document_id)
    if document is None or document.status in {"disabled", DOCUMENT_DELETING_STATUS}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    kb = await db.get(KnowledgeBase, document.knowledge_base_id)
    if kb is None or not kb.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    if user.role == "admin":
        return document, "admin"
    role = await _get_user_kb_role(db, user.id, document.knowledge_base_id)
    if role is None or role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有访问此文档的权限")
    return document, role
