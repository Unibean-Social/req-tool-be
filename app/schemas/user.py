import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    role: str
    github_login: str | None
    created_at: datetime


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
