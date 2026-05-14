import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class OrgCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrgResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID
    created_at: datetime


class OrgMemberResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    created_at: datetime


class AddMemberRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    role: Literal["owner", "member"] = "member"


class UserSearchResult(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None
    github_login: str | None
