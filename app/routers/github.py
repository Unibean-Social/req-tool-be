import hashlib
import hmac
import os
import urllib.parse
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_github_service
from app.models.user import User
from app.schemas.github import (
    BootstrapReport,
    ConnectInitResponse,
    GithubConnectRequest,
    GithubConnectionStatusResponse,
    GithubSelectRepoRequest,
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportedItem,
)
from app.schemas.response import ApiResponse
from app.services.github_service import GithubService

router = APIRouter(tags=["github"])

_CONNECT_COOKIE = "gh_connect_nonce"
_COOKIE_MAX_AGE = 600
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"


def _state_hmac_key() -> bytes:
    if settings.github_state_secret:
        return settings.github_state_secret.encode()
    return (settings.jwt_secret_key + ":github-oauth-csrf").encode()


def _make_connect_state(project_id: uuid.UUID, user_id: uuid.UUID, nonce: str) -> str:
    payload = f"{project_id}:{user_id}:{nonce}"
    sig = hmac.new(_state_hmac_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_connect_state(state: str, cookie_nonce: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        payload, sig = state.rsplit(".", 1)
        project_id_str, user_id_str, nonce = payload.split(":", 2)
    except ValueError:
        return None
    expected = hmac.new(_state_hmac_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    if not hmac.compare_digest(nonce, cookie_nonce):
        return None
    try:
        return uuid.UUID(project_id_str), uuid.UUID(user_id_str)
    except ValueError:
        return None


@router.post(
    "/projects/{project_id}/github/connect/init",
    response_model=ApiResponse[ConnectInitResponse],
    summary="Get GitHub OAuth URL for repo connection (use with window.open)",
)
async def github_connect_init(
    project_id: uuid.UUID,
    response: Response,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    nonce = os.urandom(16).hex()
    state = _make_connect_state(project_id, user.id, nonce)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_repo_connect_redirect_uri,
        "scope": "repo",
        "state": state,
    }
    redirect_url = f"{_GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    response.set_cookie(
        _CONNECT_COOKIE,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return ok(ConnectInitResponse(redirect_url=redirect_url))


@router.get("/github/connect/callback", summary="GitHub OAuth callback for repo connection")
async def github_connect_callback(
    code: str,
    state: str,
    response: Response,
    service: GithubService = Depends(get_github_service),
    gh_connect_nonce: str | None = Cookie(default=None, alias=_CONNECT_COOKIE),
):
    if not gh_connect_nonce:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing OAuth nonce cookie")
    ids = _verify_connect_state(state, gh_connect_nonce)
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state — possible CSRF")

    project_id, user_id = ids
    _secure = settings.app_env != "development"
    response.delete_cookie(_CONNECT_COOKIE, httponly=True, samesite="lax", secure=_secure)

    user_result = await service.db.execute(select(User).where(User.id == user_id))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    await require_project_access(project_id, user_obj, service.db)

    await service.complete_oauth_connect(code, project_id)
    return ok({"message": "GitHub connected — call POST /github/connect to set repo owner/name"})


@router.post(
    "/projects/{project_id}/github/connect",
    response_model=ApiResponse[GithubConnectionStatusResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Connect project to a GitHub repo via PAT",
)
async def github_connect_pat(
    project_id: uuid.UUID,
    body: GithubConnectRequest,
    user: User = Depends(current_user),
    service: GithubService = Depends(get_github_service),
):
    await require_project_access(project_id, user, service.db)
    conn = await service.connect_pat(project_id, body)
    return created(GithubConnectionStatusResponse(
        connected=True,
        repo_owner=conn.repo_owner,
        repo_name=conn.repo_name,
        bootstrap_status=conn.bootstrap_status,
    ))


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
