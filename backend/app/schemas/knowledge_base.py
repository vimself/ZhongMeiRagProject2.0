from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2048)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2048)


class KnowledgeBaseOut(BaseModel):
    id: str
    name: str
    description: str
    creator_id: str | None = None
    is_active: bool
    my_role: str | None = None
    created_at: str
    updated_at: str


class KnowledgeBaseListResponse(BaseModel):
    items: list[KnowledgeBaseOut]
    total: int
    page: int
    page_size: int


class PermissionOut(BaseModel):
    id: str
    knowledge_base_id: str
    user_id: str
    username: str = ""
    display_name: str = ""
    role: str
    created_at: str
    updated_at: str


class PermissionUserOut(BaseModel):
    id: str
    username: str
    display_name: str


class PermissionUpdateItem(BaseModel):
    user_id: str
    role: str = Field(pattern=r"^(owner|editor|viewer)$")


class PermissionUpdateRequest(BaseModel):
    permissions: list[PermissionUpdateItem]
