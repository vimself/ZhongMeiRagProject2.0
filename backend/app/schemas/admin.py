from pydantic import BaseModel, Field


class AdminUserOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    is_active: bool
    require_password_change: bool
    avatar_url: str | None = None
    last_login_at: str | None = None
    created_at: str
    updated_at: str


class AdminUserListResponse(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    page_size: int


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="user", pattern=r"^(admin|user)$")


class AdminUpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = Field(default=None, pattern=r"^(admin|user)$")
    is_active: bool | None = None
    require_password_change: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class AuditLogOut(BaseModel):
    id: str
    actor_user_id: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    ip_address: str
    details: dict[str, object]
    created_at: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int
