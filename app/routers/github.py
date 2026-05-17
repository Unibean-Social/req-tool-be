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
_GITHUB_APP_INSTALL_URL = "https://github.com/apps/{slug}/installations/new"


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
    summary="Get GitHub App install URL for repo connection",
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
    install_url = _GITHUB_APP_INSTALL_URL.format(slug=settings.github_app_slug)
    redirect_url = f"{install_url}?state={urllib.parse.quote(state)}"
    response.set_cookie(
        _CONNECT_COOKIE,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return ok(ConnectInitResponse(redirect_url=redirect_url))


@router.get("/github/connect/callback", summary="GitHub App installation callback")
async def github_connect_callback(
    installation_id: str,
    state: str,
    response: Response,
    setup_action: str = "install",
    service: GithubService = Depends(get_github_service),
    gh_connect_nonce: str | None = Cookie(default=None, alias=_CONNECT_COOKIE),
):
    if not gh_connect_nonce:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Thiếu cookie xác thực kết nối")
    ids = _verify_connect_state(state, gh_connect_nonce)
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="State không hợp lệ — có thể là tấn công CSRF")

    project_id, user_id = ids
    _secure = settings.app_env != "development"
    response.delete_cookie(_CONNECT_COOKIE, httponly=True, samesite="lax", secure=_secure)

    if setup_action not in ("install", "update"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"setup_action không hợp lệ: {setup_action}")

    user_result = await service.db.execute(select(User).where(User.id == user_id))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Không tìm thấy người dùng")
    await require_project_access(project_id, user_obj, service.db)

    await service.complete_app_connect(installation_id, project_id)
    return ok({"message": "Đã kết nối GitHub App — gọi PATCH /github/connect để thiết lập tên owner/repo"})


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
