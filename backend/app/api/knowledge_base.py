from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import current_user
from app.api.knowledge_base_deps import (
    RequireEditor,
    RequireOwner,
    RequireViewer,
    _get_user_kb_role,
)
from app.db.session import get_db_session
from app.models.auth import User
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    PermissionOut,
    PermissionUpdateRequest,
    PermissionUserOut,
)

router = APIRouter(prefix="/api/v2/knowledge-bases", tags=["knowledge-base"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(current_user)]


def _kb_out(kb: KnowledgeBase, my_role: str | None = None) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        creator_id=kb.creator_id,
        is_active=kb.is_active,
        my_role=my_role,
        created_at=kb.created_at.isoformat(),
        updated_at=kb.updated_at.isoformat(),
    )


def _permission_out(
    permission: KnowledgeBasePermission,
    users_map: dict[str, tuple[str, str]],
) -> PermissionOut:
    username, display_name = users_map.get(permission.user_id, ("", ""))
    return PermissionOut(
        id=permission.id,
        knowledge_base_id=permission.knowledge_base_id,
        user_id=permission.user_id,
        username=username,
        display_name=display_name,
        role=permission.role,
        created_at=permission.created_at.isoformat(),
        updated_at=permission.updated_at.isoformat(),
    )


async def _users_map_for_permissions(
    db: AsyncSession,
    permissions: list[KnowledgeBasePermission],
) -> dict[str, tuple[str, str]]:
    user_ids = [permission.user_id for permission in permissions]
    if not user_ids:
        return {}
    user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    return {user.id: (user.username, user.display_name) for user in user_rows}


async def _load_permissions(
    db: AsyncSession,
    knowledge_base_id: str,
) -> list[KnowledgeBasePermission]:
    return list(
        (
            await db.execute(
                select(KnowledgeBasePermission).where(
                    KnowledgeBasePermission.knowledge_base_id == knowledge_base_id
                )
            )
        )
        .scalars()
        .all()
    )


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=256),
) -> KnowledgeBaseListResponse:
    # Non-admin users only see KBs where they have a permission record
    if user.role == "admin":
        base_query = select(KnowledgeBase).where(KnowledgeBase.is_active == True)  # noqa: E712
        count_query = (
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.is_active == True)  # noqa: E712
        )
    else:
        perm_subq = (
            select(KnowledgeBasePermission.knowledge_base_id)
            .where(KnowledgeBasePermission.user_id == user.id)
            .subquery()
        )
        base_query = select(KnowledgeBase).where(
            KnowledgeBase.is_active == True,  # noqa: E712
            KnowledgeBase.id.in_(select(perm_subq.c.knowledge_base_id)),
        )
        count_query = (
            select(func.count())
            .select_from(KnowledgeBase)
            .where(
                KnowledgeBase.is_active == True,  # noqa: E712
                KnowledgeBase.id.in_(select(perm_subq.c.knowledge_base_id)),
            )
        )

    if search:
        pattern = f"%{search}%"
        condition = KnowledgeBase.name.ilike(pattern) | KnowledgeBase.description.ilike(pattern)
        base_query = base_query.where(condition)
        count_query = count_query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    offset = (page - 1) * page_size
    base_query = (
        base_query.order_by(KnowledgeBase.created_at.desc()).offset(offset).limit(page_size)
    )
    result = await db.execute(base_query)
    kbs = list(result.scalars().all())

    # Attach my_role for each KB
    items: list[KnowledgeBaseOut] = []
    for kb in kbs:
        if user.role == "admin":
            my_role: str | None = "admin"
        else:
            my_role = await _get_user_kb_role(db, user.id, kb.id)
        items.append(_kb_out(kb, my_role=my_role))

    return KnowledgeBaseListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    request: Request,
    body: KnowledgeBaseCreate,
    user: CurrentUser,
    db: DbSession,
) -> KnowledgeBaseOut:
    kb = KnowledgeBase(
        name=body.name.strip(),
        description=body.description.strip(),
        creator_id=user.id,
    )
    db.add(kb)
    await db.flush()

    # Auto-assign owner to creator
    perm = KnowledgeBasePermission(
        knowledge_base_id=kb.id,
        user_id=user.id,
        role="owner",
    )
    db.add(perm)

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="knowledge_base.create",
        target_type="knowledge_base",
        target_id=kb.id,
        request=request,
        details={"name": kb.name},
    )
    await db.commit()
    await db.refresh(kb)
    return _kb_out(kb, my_role="owner")


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    result: RequireViewer,
) -> KnowledgeBaseOut:
    kb, role = result
    return _kb_out(kb, my_role=role)


@router.put("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: str,
    request: Request,
    body: KnowledgeBaseUpdate,
    result: RequireEditor,
    user: CurrentUser,
    db: DbSession,
) -> KnowledgeBaseOut:
    kb, role = result
    changes: dict[str, object] = {}
    if body.name is not None:
        kb.name = body.name.strip()
        changes["name"] = kb.name
    if body.description is not None:
        kb.description = body.description.strip()
        changes["description"] = kb.description

    if not changes:
        return _kb_out(kb, my_role=role)

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="knowledge_base.update",
        target_type="knowledge_base",
        target_id=kb.id,
        request=request,
        details=changes,
    )
    await db.commit()
    await db.refresh(kb)
    return _kb_out(kb, my_role=role)


@router.delete("/{kb_id}", response_model=KnowledgeBaseOut)
async def disable_knowledge_base(
    kb_id: str,
    request: Request,
    result: RequireOwner,
    user: CurrentUser,
    db: DbSession,
) -> KnowledgeBaseOut:
    kb, role = result
    kb.is_active = False

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="knowledge_base.disable",
        target_type="knowledge_base",
        target_id=kb.id,
        request=request,
        details={"name": kb.name},
    )
    await db.commit()
    await db.refresh(kb)
    return _kb_out(kb, my_role=role)


@router.get("/{kb_id}/permissions", response_model=list[PermissionOut])
async def list_permissions(
    result: RequireViewer,
    db: DbSession,
) -> list[PermissionOut]:
    kb, _role = result
    rows = await _load_permissions(db, kb.id)
    users_map = await _users_map_for_permissions(db, rows)
    return [_permission_out(row, users_map) for row in rows]


@router.get("/{kb_id}/permission-candidates", response_model=list[PermissionUserOut])
async def list_permission_candidates(
    result: RequireOwner,
    db: DbSession,
    search: str = Query("", max_length=128),
) -> list[PermissionUserOut]:
    _kb, _role = result
    query = select(User).where(User.is_active == True)  # noqa: E712
    if search:
        pattern = f"%{search}%"
        query = query.where(User.username.ilike(pattern) | User.display_name.ilike(pattern))
    query = query.order_by(User.created_at.desc()).limit(500)
    users = (await db.execute(query)).scalars().all()
    return [
        PermissionUserOut(id=user.id, username=user.username, display_name=user.display_name)
        for user in users
    ]


@router.put("/{kb_id}/permissions", response_model=list[PermissionOut])
async def update_permissions(
    kb_id: str,
    request: Request,
    body: PermissionUpdateRequest,
    result: RequireOwner,
    user: CurrentUser,
    db: DbSession,
) -> list[PermissionOut]:
    kb, _role = result

    incoming_user_ids = [permission.user_id for permission in body.permissions]
    if len(set(incoming_user_ids)) != len(incoming_user_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="权限列表中存在重复用户",
        )

    if incoming_user_ids:
        existing_users = (
            await db.execute(select(User.id).where(User.id.in_(incoming_user_ids)))
        ).scalars()
        missing_user_ids = set(incoming_user_ids) - set(existing_users.all())
        if missing_user_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="权限列表中存在不存在的用户",
            )

    # Load existing permissions
    existing_rows = await _load_permissions(db, kb.id)
    existing_map: dict[str, KnowledgeBasePermission] = {r.user_id: r for r in existing_rows}

    incoming_user_id_set = set(incoming_user_ids)

    # Prevent removing the last owner
    current_owner_ids = {r.user_id for r in existing_rows if r.role == "owner"}
    incoming_owner_ids = {p.user_id for p in body.permissions if p.role == "owner"}
    # After applying changes, who will be owner?
    # Keep owners that are not in incoming list (unchanged) + incoming owners
    owners_not_in_incoming = current_owner_ids - incoming_user_id_set
    final_owner_ids = owners_not_in_incoming | incoming_owner_ids
    if not final_owner_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能移除最后一个 owner",
        )

    # Apply changes
    for item in body.permissions:
        if item.user_id in existing_map:
            existing_map[item.user_id].role = item.role
        else:
            db.add(
                KnowledgeBasePermission(
                    knowledge_base_id=kb.id,
                    user_id=item.user_id,
                    role=item.role,
                )
            )

    # Remove permissions not in incoming list
    for user_id, perm in existing_map.items():
        if user_id not in incoming_user_id_set:
            await db.delete(perm)

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="knowledge_base.permissions.update",
        target_type="knowledge_base",
        target_id=kb.id,
        request=request,
        details={"user_count": len(body.permissions)},
    )
    await db.commit()

    # Re-query and return
    rows = await _load_permissions(db, kb.id)
    users_map = await _users_map_for_permissions(db, rows)
    return [_permission_out(row, users_map) for row in rows]


# ── Admin view: list ALL knowledge bases ───────────────────────────────

admin_router = APIRouter(prefix="/api/v2/admin/knowledge-bases", tags=["admin"])


@admin_router.get("", response_model=KnowledgeBaseListResponse)
async def admin_list_knowledge_bases(
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=256),
    is_active: bool | None = Query(None),
) -> KnowledgeBaseListResponse:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")

    query = select(KnowledgeBase)
    count_query = select(func.count()).select_from(KnowledgeBase)

    if search:
        pattern = f"%{search}%"
        condition = KnowledgeBase.name.ilike(pattern) | KnowledgeBase.description.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)
    if is_active is not None:
        query = query.where(KnowledgeBase.is_active == is_active)
        count_query = count_query.where(KnowledgeBase.is_active == is_active)

    total = (await db.execute(count_query)).scalar_one()
    offset = (page - 1) * page_size
    query = query.order_by(KnowledgeBase.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    kbs = list(result.scalars().all())

    return KnowledgeBaseListResponse(
        items=[_kb_out(kb) for kb in kbs],
        total=total,
        page=page,
        page_size=page_size,
    )


@admin_router.get("/{kb_id}/permissions", response_model=list[PermissionOut])
async def admin_list_permissions(
    kb_id: str,
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
) -> list[PermissionOut]:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    rows = await _load_permissions(db, kb.id)
    users_map = await _users_map_for_permissions(db, rows)
    return [_permission_out(row, users_map) for row in rows]
