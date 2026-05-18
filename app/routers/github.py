import os
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, Response, status

from app.config import settings
from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_github_service
from app.models.user import User
from app.routers.github_auth import (
    GITHUB_AUTHORIZE_URL,
    _CONNECT_COOKIE,
    _COOKIE_MAX_AGE,
    make_connect_state,
)
from app.schemas.github import (
    BootstrapReport,
    ConnectInitResponse,
    GithubConnectionStatusResponse,
    GithubSelectRepoRequest,
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportedItem,
)
from app.schemas.response import ApiResponse
from app.services.github_service import GithubService

router = APIRouter(tags=["github"])


@router.post(
    "/projects/{project_id}/github/connect/init",
    response_model=ApiResponse[ConnectInitResponse],
    summary="Get GitHub OAuth authorize URL for repo connection",
)
async def github_connect_init(
    project_id: uuid.UUID,
    response: Response,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    nonce = os.urandom(16).hex()
    state = make_connect_state(project_id, user.id, nonce)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": "repo",
        "state": state,
    }
    redirect_url = f"{GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    response.set_cookie(
        _CONNECT_COOKIE,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return ok(ConnectInitResponse(redirect_url=redirect_url))


@router.patch(
    "/projects/{project_id}/github/connect",
    response_model=ApiResponse[GithubConnectionStatusResponse],
)
async def github_select_repo(
    project_id: uuid.UUID,
    body: GithubSelectRepoRequest,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    conn = await service.select_repo(project_id, body)
    return ok(GithubConnectionStatusResponse(
        connected=True,
        repo_owner=conn.repo_owner,
        repo_name=conn.repo_name,
        bootstrap_status=conn.bootstrap_status,
    ))


@router.get("/projects/{project_id}/github/repos", response_model=ApiResponse[list[dict]])
async def github_list_repos(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list_repos(project_id))


@router.get(
    "/projects/{project_id}/github/status",
    response_model=ApiResponse[GithubConnectionStatusResponse],
)
async def github_status(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.get_status(project_id))


@router.post(
    "/projects/{project_id}/github/bootstrap",
    response_model=ApiResponse[BootstrapReport],
)
async def github_bootstrap(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.bootstrap(project_id))


@router.get(
    "/projects/{project_id}/github/import/preview",
    response_model=ApiResponse[ImportPreviewResponse],
)
async def github_import_preview(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.import_preview(project_id))


@router.post(
    "/projects/{project_id}/github/import/confirm",
    response_model=ApiResponse[list[ImportedItem]],
    status_code=status.HTTP_201_CREATED,
)
async def github_import_confirm(
    project_id: uuid.UUID,
    body: ImportConfirmRequest,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    return created(await service.import_confirm(project_id, body))
