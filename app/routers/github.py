import json
import os
import urllib.parse
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.config import settings
from app.core.guards import require_project_access
from app.core.responses import created, ok
from app.deps import current_user, get_github_service
from app.models.user import User
from app.routers.github_auth import (
    _CONNECT_COOKIE,
    _COOKIE_MAX_AGE,
    make_connect_state,
    verify_connect_state,
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

_GITHUB_APP_INSTALL_URL = "https://github.com/apps/{slug}/installations/new"


@router.post(
    "/projects/{project_id}/github/connect/init",
    response_model=ApiResponse[ConnectInitResponse],
    summary="Get GitHub App installation URL for repo connection",
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
    base_url = _GITHUB_APP_INSTALL_URL.format(slug=settings.github_app_slug)
    redirect_url = f"{base_url}?{urllib.parse.urlencode({'state': state})}"
    response.set_cookie(
        _CONNECT_COOKIE,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return ok(ConnectInitResponse(redirect_url=redirect_url))


@router.get("/github/app/setup", response_class=HTMLResponse, include_in_schema=False)
async def github_app_setup(
    response: Response,
    installation_id: str | None = None,
    setup_action: str | None = None,
    state: str | None = None,
    gh_connect_nonce: str | None = Cookie(default=None, alias=_CONNECT_COOKIE),
    service: GithubService = Depends(get_github_service),
):
    target_origin = settings.cors_origins[0] if settings.cors_origins else "*"
    _secure = settings.app_env != "development"

    def _err(error: str, description: str | None = None) -> HTMLResponse:
        payload = json.dumps({"type": "github_error", "error": error, "description": description})
        return HTMLResponse(f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage({payload}, {json.dumps(target_origin)});
window.close();
</script><p>Lỗi: {error}</p></body></html>""")

    if setup_action == "delete":
        return _err("installation_deleted", "GitHub App đã bị gỡ cài đặt")

    if not installation_id:
        return _err("missing_installation_id", "Không nhận được installation_id từ GitHub")

    if not state or not gh_connect_nonce:
        return _err("missing_state", "Thiếu state hoặc cookie xác thực")

    response.delete_cookie(_CONNECT_COOKIE, httponly=True, samesite="lax", secure=_secure)

    ids = verify_connect_state(state, gh_connect_nonce)
    if not ids:
        return _err("invalid_state", "State không hợp lệ — có thể là tấn công CSRF")

    project_id, user_id = ids

    user_result = await service.db.execute(select(User).where(User.id == user_id))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        return _err("unauthorized", "Không tìm thấy người dùng")

    try:
        await require_project_access(project_id, user_obj, service.db)
    except HTTPException:
        return _err("forbidden", "Không có quyền truy cập project")

    try:
        await service.complete_app_install(installation_id, project_id, user_id)
    except HTTPException as exc:
        return _err("connect_failed", exc.detail)

    payload = json.dumps({"type": "github_connect", "project_id": str(project_id)})
    return HTMLResponse(f"""<!doctype html><html><body><script>
window.opener && window.opener.postMessage({payload}, {json.dumps(target_origin)});
window.close();
</script><p>Đang đóng cửa sổ...</p></body></html>""")


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
