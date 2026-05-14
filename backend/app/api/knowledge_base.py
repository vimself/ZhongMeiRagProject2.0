from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _record_audit
from app.api.deps import current_user
from app.api.knowledge_base_deps import (
    RequireEditor,
    RequireOwner,
    RequireViewer,
    _get_user_kb_role,
)
from app.core.timezone import beijing_now, isoformat_beijing
from app.db.session import get_db_session
from app.models.auth import User
from app.models.document import Document
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
from app.services.deletion import (
    DOCUMENT_DELETING_STATUS,
    collect_document_deletion_resources,
    delete_artifact_files,
    hard_delete_knowledge_base,
    release_document_ingest_resources,
    request_document_deletion,
)

router = APIRouter(prefix="/api/v2/knowledge-bases", tags=["knowledge-base"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(current_user)]


def _kb_out(
    kb: KnowledgeBase,
    my_role: str | None = None,
    creator_username: str = "",
    creator_name: str = "",
    document_count: int = 0,
    active_document_count: int = 0,
    permission_count: int = 0,
) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        creator_id=kb.creator_id,
        creator_username=creator_username,
        creator_name=creator_name,
        is_active=kb.is_active,
        my_role=my_role,
        document_count=document_count,
        active_document_count=active_document_count,
        permission_count=permission_count,
        deleted_at=isoformat_beijing(kb.updated_at) if not kb.is_active else None,
        created_at=isoformat_beijing(kb.created_at),
        updated_at=isoformat_beijing(kb.updated_at),
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
        created_at=isoformat_beijing(permission.created_at),
        updated_at=isoformat_beijing(permission.updated_at),
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


async def _user_identities_for_users(
    db: AsyncSession,
    user_ids: list[str],
) -> dict[str, tuple[str, str]]:
    compact_ids = [user_id for user_id in dict.fromkeys(user_ids) if user_id]
    if not compact_ids:
        return {}
    user_rows = (await db.execute(select(User).where(User.id.in_(compact_ids)))).scalars().all()
    return {user.id: (user.username, user.display_name) for user in user_rows}


async def _creator_identity_for_kb(
    db: AsyncSession,
    kb: KnowledgeBase,
) -> tuple[str, str]:
    creator_identities = await _user_identities_for_users(
        db,
        [kb.creator_id] if kb.creator_id else [],
    )
    return creator_identities.get(kb.creator_id or "", ("", ""))


async def _admin_kb_archive_counts(
    db: AsyncSession,
    kb_ids: list[str],
) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    if not kb_ids:
        return {}, {}
    doc_rows = (
        await db.execute(
            select(
                Document.knowledge_base_id,
                func.count(Document.id),
                func.sum(
                    case(
                        (Document.status.notin_(("disabled", DOCUMENT_DELETING_STATUS)), 1),
                        else_=0,
                    )
                ),
            )
            .where(Document.knowledge_base_id.in_(kb_ids))
            .group_by(Document.knowledge_base_id)
        )
    ).all()
    permission_rows = (
        await db.execute(
            select(
                KnowledgeBasePermission.knowledge_base_id, func.count(KnowledgeBasePermission.id)
            )
            .where(KnowledgeBasePermission.knowledge_base_id.in_(kb_ids))
            .group_by(KnowledgeBasePermission.knowledge_base_id)
        )
    ).all()
    document_counts = {str(row[0]): (int(row[1] or 0), int(row[2] or 0)) for row in doc_rows}
    permission_counts = {str(row[0]): int(row[1] or 0) for row in permission_rows}
    return document_counts, permission_counts


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


async def _permission_candidates(
    db: AsyncSession,
    search: str = "",
) -> list[PermissionUserOut]:
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


async def _apply_permission_update(
    kb: KnowledgeBase,
    request: Request,
    body: PermissionUpdateRequest,
    user: User,
    db: AsyncSession,
) -> list[PermissionOut]:
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

    existing_rows = await _load_permissions(db, kb.id)
    existing_map: dict[str, KnowledgeBasePermission] = {r.user_id: r for r in existing_rows}

    incoming_user_id_set = set(incoming_user_ids)
    incoming_owner_ids = {p.user_id for p in body.permissions if p.role == "owner"}
    if not incoming_owner_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能移除最后一个 owner",
        )

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
        details={"name": kb.name, "user_count": len(body.permissions)},
    )
    await db.commit()

    rows = await _load_permissions(db, kb.id)
    users_map = await _users_map_for_permissions(db, rows)
    return [_permission_out(row, users_map) for row in rows]


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
    creator_identities = await _user_identities_for_users(
        db,
        [kb.creator_id for kb in kbs if kb.creator_id],
    )

    # Attach my_role for each KB
    items: list[KnowledgeBaseOut] = []
    for kb in kbs:
        if user.role == "admin":
            my_role: str | None = "admin"
        else:
            my_role = await _get_user_kb_role(db, user.id, kb.id)
        creator_username, creator_name = creator_identities.get(kb.creator_id or "", ("", ""))
        items.append(
            _kb_out(
                kb,
                my_role=my_role,
                creator_username=creator_username,
                creator_name=creator_name,
            )
        )

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
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="只有管理员可以创建知识库"
        )

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
    return _kb_out(
        kb,
        my_role="admin",
        creator_username=user.username,
        creator_name=user.display_name,
    )


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    result: RequireViewer,
    db: DbSession,
) -> KnowledgeBaseOut:
    kb, role = result
    creator_username, creator_name = await _creator_identity_for_kb(db, kb)
    return _kb_out(
        kb,
        my_role=role,
        creator_username=creator_username,
        creator_name=creator_name,
    )


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
        creator_username, creator_name = await _creator_identity_for_kb(db, kb)
        return _kb_out(
            kb,
            my_role=role,
            creator_username=creator_username,
            creator_name=creator_name,
        )

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
    creator_username, creator_name = await _creator_identity_for_kb(db, kb)
    return _kb_out(
        kb,
        my_role=role,
        creator_username=creator_username,
        creator_name=creator_name,
    )


@router.delete("/{kb_id}", response_model=KnowledgeBaseOut)
async def delete_knowledge_base(
    kb_id: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> KnowledgeBaseOut:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="只有管理员可以删除知识库"
        )

    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    documents = list(await db.scalars(select(Document).where(Document.knowledge_base_id == kb.id)))
    document_ids = [document.id for document in documents]
    active_document_count = sum(
        1 for document in documents if document.status not in {"disabled", DOCUMENT_DELETING_STATUS}
    )
    resources = await collect_document_deletion_resources(db, document_ids)
    creator_username, creator_name = await _creator_identity_for_kb(db, kb)
    deleted_payload = _kb_out(
        kb,
        my_role="admin",
        creator_username=creator_username,
        creator_name=creator_name,
        document_count=len(document_ids),
        active_document_count=active_document_count,
    )
    deleted_payload.is_active = False
    deleted_payload.deleted_at = isoformat_beijing(beijing_now())

    await _record_audit(
        db,
        actor_user_id=user.id,
        action="knowledge_base.delete",
        target_type="knowledge_base",
        target_id=kb.id,
        request=request,
        details={"name": kb.name, "document_count": len(document_ids)},
    )
    await request_document_deletion(db, document_ids)
    await db.commit()
    await release_document_ingest_resources(resources)
    await hard_delete_knowledge_base(db, kb.id)
    await db.commit()
    delete_artifact_files(resources.artifact_paths)
    return deleted_payload


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
    result: RequireViewer,
    user: CurrentUser,
    db: DbSession,
    search: str = Query("", max_length=128),
) -> list[PermissionUserOut]:
    _kb, _role = result
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return await _permission_candidates(db, search)


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
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return await _apply_permission_update(kb, request, body, user, db)


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

    active_filter = True if is_active is None else is_active
    query = select(KnowledgeBase).where(KnowledgeBase.is_active == active_filter)
    count_query = (
        select(func.count())
        .select_from(KnowledgeBase)
        .where(KnowledgeBase.is_active == active_filter)
    )

    if search:
        pattern = f"%{search}%"
        condition = KnowledgeBase.name.ilike(pattern) | KnowledgeBase.description.ilike(pattern)
        query = query.where(condition)
        count_query = count_query.where(condition)
    total = (await db.execute(count_query)).scalar_one()
    offset = (page - 1) * page_size
    query = query.order_by(KnowledgeBase.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    kbs = list(result.scalars().all())
    creator_identities = await _user_identities_for_users(
        db,
        [kb.creator_id for kb in kbs if kb.creator_id],
    )
    document_counts, permission_counts = await _admin_kb_archive_counts(db, [kb.id for kb in kbs])

    return KnowledgeBaseListResponse(
        items=[
            _kb_out(
                kb,
                creator_username=creator_identities.get(kb.creator_id or "", ("", ""))[0],
                creator_name=creator_identities.get(kb.creator_id or "", ("", ""))[1],
                document_count=document_counts.get(kb.id, (0, 0))[0],
                active_document_count=document_counts.get(kb.id, (0, 0))[1],
                permission_count=permission_counts.get(kb.id, 0),
            )
            for kb in kbs
        ],
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


@admin_router.get("/{kb_id}/permission-candidates", response_model=list[PermissionUserOut])
async def admin_list_permission_candidates(
    kb_id: str,
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
    search: str = Query("", max_length=128),
) -> list[PermissionUserOut]:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or not kb.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return await _permission_candidates(db, search)


@admin_router.put("/{kb_id}/permissions", response_model=list[PermissionOut])
async def admin_update_permissions(
    kb_id: str,
    request: Request,
    body: PermissionUpdateRequest,
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
) -> list[PermissionOut]:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or not kb.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="知识库不存在")
    return await _apply_permission_update(kb, request, body, user, db)
