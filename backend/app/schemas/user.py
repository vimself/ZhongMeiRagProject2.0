from pydantic import BaseModel, Field


class UserProfileOut(BaseModel):
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


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)


class ChangePasswordViaUserRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)
