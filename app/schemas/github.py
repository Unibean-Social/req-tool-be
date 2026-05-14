import uuid
from typing import Literal

from pydantic import BaseModel, field_validator


class ConnectInitResponse(BaseModel):
    redirect_url: str


class GithubConnectRequest(BaseModel):
    repo_owner: str
    repo_name: str
    access_token: str


class GithubSelectRepoRequest(BaseModel):
    repo_owner: str
    repo_name: str


class GithubConnectionStatusResponse(BaseModel):
    connected: bool
    repo_owner: str | None = None
    repo_name: str | None = None
    bootstrap_status: str


class BootstrapResourceResult(BaseModel):
    name: str
    status: Literal["created", "already_present", "failed"]
    detail: str | None = None


class BootstrapReport(BaseModel):
    labels: list[BootstrapResourceResult]
    milestone: BootstrapResourceResult
    board: BootstrapResourceResult


class GithubIssuePreview(BaseModel):
    github_issue_number: int
    title: str
    body: str | None
    labels: list[str]


class ImportPreviewResponse(BaseModel):
    epics: list[GithubIssuePreview] = []
    features: list[GithubIssuePreview] = []
    stories: list[GithubIssuePreview] = []
    tasks: list[GithubIssuePreview] = []
    unclassified: list[GithubIssuePreview] = []


class ImportMappingItem(BaseModel):
    github_issue_number: int
    item_type: Literal["epic", "feature", "story", "task"]
    title: str | None = None
    parent_github_issue_number: int | None = None

class ImportConfirmRequest(BaseModel):
    mappings: list[ImportMappingItem]

    @field_validator("mappings")
    @classmethod
    def check_epic_parents(cls, v: list[ImportMappingItem]) -> list[ImportMappingItem]:
        for item in v:
            if item.item_type == "epic" and item.parent_github_issue_number is not None:
                raise ValueError(f"Issue #{item.github_issue_number}: epics cannot have a parent")
            if item.item_type != "epic" and item.parent_github_issue_number is None:
                raise ValueError(
                    f"Issue #{item.github_issue_number}: non-epic items require parent_github_issue_number"
                )
        return v


class ImportedItem(BaseModel):
    github_issue_number: int
    item_type: str
    prefix: str
    title: str
    db_id: uuid.UUID
