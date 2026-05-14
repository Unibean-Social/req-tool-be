import hashlib
import hmac
import os
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import decrypt_token, encrypt_token
from app.core.github_client import (
    BOARD_COLUMNS,
    BOARD_TITLE,
    REQFLOW_LABELS,
    SPRINT_MILESTONE_TITLE,
    GithubClient,
)
from app.core.responses import created, ok
from app.database import get_db
from app.deps import current_user
from app.models.github_connection import GithubConnection
from app.models.organization import OrgMember
from app.models.project import Project
from app.models.requirements import (
    AcceptanceCriteria,
    Epic,
    Feature,
    Story,
    Task,
)
from app.models.user import User
from app.schemas.github import (
    BootstrapReport,
    BootstrapResourceResult,
    GithubConnectRequest,
    GithubConnectionStatusResponse,
    GithubIssuePreview,
    GithubSelectRepoRequest,
    ImportConfirmRequest,
    ImportPreviewResponse,
    ImportedItem,
)
from app.schemas.response import ApiResponse

router = APIRouter(tags=["github"])

_CONNECT_COOKIE = "gh_connect_nonce"
_COOKIE_MAX_AGE = 600
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"


# ── Shared guards ─────────────────────────────────────────────────────────────


async def _require_project_access(project_id: uuid.UUID, user: User, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    member = await db.execute(
        select(OrgMember).where(OrgMember.org_id == project.org_id, OrgMember.user_id == user.id)
    )
    if not member.scalar_one_or_none():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not a member of this project's organization")
    return project


async def _require_connection(project_id: uuid.UUID, db: AsyncSession) -> GithubConnection:
    result = await db.execute(
        select(GithubConnection).where(GithubConnection.project_id == project_id)
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.access_token:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No GitHub connection — connect the project first")
    return conn


def _get_client(conn: GithubConnection) -> GithubClient:
    token = decrypt_token(conn.access_token)
    if not token:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Stored GitHub token could not be decrypted")
    return GithubClient(token)


# ── State helpers (OAuth CSRF protection) ────────────────────────────────────


def _state_hmac_key() -> bytes:
    """Return the HMAC key for OAuth state tokens.

    Uses GITHUB_STATE_SECRET when configured; falls back to a domain-namespaced
    derivative of jwt_secret_key in development so the two secrets are never
    interchangeable even when only one key is set.
    """
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


# ── Connect — OAuth redirect ──────────────────────────────────────────────────


@router.get("/projects/{project_id}/github/connect", summary="Redirect to GitHub OAuth (repo scope)")
async def github_connect_redirect(
    project_id: uuid.UUID,
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    nonce = os.urandom(16).hex()
    state = _make_connect_state(project_id, user.id, nonce)
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_repo_connect_redirect_uri,
        "scope": "repo",
        "state": state,
    }
    redirect = RedirectResponse(f"{_GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")
    redirect.set_cookie(
        _CONNECT_COOKIE,
        nonce,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
    )
    return redirect


@router.get("/github/connect/callback", summary="GitHub OAuth callback for repo connection")
async def github_connect_callback(
    code: str,
    state: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
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

    # Re-verify the user still exists and is still a member of this project's org.
    # Membership may have been revoked after the OAuth flow was initiated.
    user_result = await db.execute(select(User).where(User.id == user_id))
    user_obj = user_result.scalar_one_or_none()
    if not user_obj:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    await _require_project_access(project_id, user_obj, db)

    import httpx
    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(
                _GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": settings.github_repo_connect_redirect_uri,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            token_resp.raise_for_status()
        except Exception:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="GitHub token exchange failed")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="GitHub did not return an access token")

    encrypted = encrypt_token(access_token)
    result = await db.execute(select(GithubConnection).where(GithubConnection.project_id == project_id))
    conn = result.scalar_one_or_none()
    if conn:
        conn.access_token = encrypted
        conn.bootstrap_status = "not_started"
    else:
        conn = GithubConnection(
            project_id=project_id,
            repo_owner="",
            repo_name="",
            access_token=encrypted,
            bootstrap_status="not_started",
        )
        db.add(conn)
    await db.flush()
    return ok({"message": "GitHub connected — call POST /github/connect to set repo owner/name"})


# ── Connect — direct PAT (development / simpler path) ────────────────────────


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
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)

    gh = GithubClient(body.access_token)
    try:
        await gh.get(f"/repos/{body.repo_owner}/{body.repo_name}")
    except HTTPException as exc:
        raise HTTPException(exc.status_code, detail=f"Cannot access repo: {exc.detail}")

    encrypted = encrypt_token(body.access_token)
    result = await db.execute(select(GithubConnection).where(GithubConnection.project_id == project_id))
    conn = result.scalar_one_or_none()

    if conn:
        conn.repo_owner = body.repo_owner
        conn.repo_name = body.repo_name
        conn.access_token = encrypted
        conn.bootstrap_status = "not_started"
    else:
        conn = GithubConnection(
            project_id=project_id,
            repo_owner=body.repo_owner,
            repo_name=body.repo_name,
            access_token=encrypted,
            bootstrap_status="not_started",
        )
        db.add(conn)

    await db.flush()
    return created(GithubConnectionStatusResponse(
        connected=True,
        repo_owner=conn.repo_owner,
        repo_name=conn.repo_name,
        bootstrap_status=conn.bootstrap_status,
    ))


# ── Select repo after OAuth connect (token already stored) ───────────────────


@router.patch(
    "/projects/{project_id}/github/connect",
    response_model=ApiResponse[GithubConnectionStatusResponse],
)
async def github_select_repo(
    project_id: uuid.UUID,
    body: GithubSelectRepoRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set repo_owner/repo_name after OAuth callback has already stored the token."""
    await _require_project_access(project_id, user, db)
    conn = await _require_connection(project_id, db)
    gh = _get_client(conn)
    try:
        await gh.get(f"/repos/{body.repo_owner}/{body.repo_name}")
    except HTTPException as exc:
        raise HTTPException(exc.status_code, detail=f"Cannot access repo: {exc.detail}")
    conn.repo_owner = body.repo_owner
    conn.repo_name = body.repo_name
    await db.flush()
    return ok(GithubConnectionStatusResponse(
        connected=True,
        repo_owner=conn.repo_owner,
        repo_name=conn.repo_name,
        bootstrap_status=conn.bootstrap_status,
    ))


# ── List accessible repos (requires existing connection token) ────────────────


@router.get("/projects/{project_id}/github/repos", response_model=ApiResponse[list[dict]])
async def github_list_repos(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """List repos accessible by the stored OAuth token — call after connect redirect."""
    await _require_project_access(project_id, user, db)
    conn = await _require_connection(project_id, db)
    gh = _get_client(conn)
    repos = await gh.get("/user/repos", params={"sort": "updated", "per_page": 50})
    return ok([{"full_name": r["full_name"], "private": r["private"], "html_url": r["html_url"]} for r in repos])


# ── Connection status ─────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/github/status",
    response_model=ApiResponse[GithubConnectionStatusResponse],
)
async def github_status(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    result = await db.execute(select(GithubConnection).where(GithubConnection.project_id == project_id))
    conn = result.scalar_one_or_none()
    if not conn:
        return ok(GithubConnectionStatusResponse(connected=False, bootstrap_status="not_started"))
    return ok(GithubConnectionStatusResponse(
        connected=bool(conn.access_token),
        repo_owner=conn.repo_owner or None,
        repo_name=conn.repo_name or None,
        bootstrap_status=conn.bootstrap_status,
    ))


# ── Bootstrap ─────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/github/bootstrap",
    response_model=ApiResponse[BootstrapReport],
)
async def github_bootstrap(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    conn = await _require_connection(project_id, db)
    gh = _get_client(conn)

    conn.bootstrap_status = "in_progress"
    await db.flush()

    label_results = await _bootstrap_labels(gh, conn.repo_owner, conn.repo_name)
    milestone_result = await _bootstrap_milestone(gh, conn.repo_owner, conn.repo_name)
    board_result = await _bootstrap_board(gh, conn.repo_owner, conn.repo_name)

    all_ok = all(r.status != "failed" for r in label_results) and \
              milestone_result.status != "failed" and \
              board_result.status != "failed"
    conn.bootstrap_status = "completed" if all_ok else "in_progress"
    await db.flush()

    report = BootstrapReport(
        labels=label_results,
        milestone=milestone_result,
        board=board_result,
    )
    return ok(report)


async def _bootstrap_labels(gh: GithubClient, owner: str, repo: str) -> list[BootstrapResourceResult]:
    try:
        existing = await gh.get(f"/repos/{owner}/{repo}/labels", params={"per_page": 100})
        existing_names = {lbl["name"] for lbl in existing}
    except HTTPException:
        existing_names = set()

    results: list[BootstrapResourceResult] = []
    for lbl in REQFLOW_LABELS:
        if lbl["name"] in existing_names:
            results.append(BootstrapResourceResult(name=lbl["name"], status="already_present"))
            continue
        try:
            await gh.post(f"/repos/{owner}/{repo}/labels", json=lbl)
            results.append(BootstrapResourceResult(name=lbl["name"], status="created"))
        except HTTPException as exc:
            results.append(BootstrapResourceResult(name=lbl["name"], status="failed", detail=exc.detail))
    return results


async def _bootstrap_milestone(gh: GithubClient, owner: str, repo: str) -> BootstrapResourceResult:
    try:
        milestones = await gh.get(f"/repos/{owner}/{repo}/milestones", params={"state": "open"})
        if any(m["title"] == SPRINT_MILESTONE_TITLE for m in milestones):
            return BootstrapResourceResult(name=SPRINT_MILESTONE_TITLE, status="already_present")
        due = (datetime.now(timezone.utc) + timedelta(weeks=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        await gh.post(f"/repos/{owner}/{repo}/milestones", json={
            "title": SPRINT_MILESTONE_TITLE,
            "due_on": due,
            "description": "ReqFlow Sprint 1",
        })
        return BootstrapResourceResult(name=SPRINT_MILESTONE_TITLE, status="created")
    except HTTPException as exc:
        return BootstrapResourceResult(name=SPRINT_MILESTONE_TITLE, status="failed", detail=exc.detail)


async def _bootstrap_board(gh: GithubClient, owner: str, repo: str) -> BootstrapResourceResult:
    try:
        # Get repo node id and owner node id via GraphQL
        repo_data = await gh.graphql(
            """
            query($owner: String!, $name: String!) {
              repository(owner: $owner, name: $name) {
                id
                owner { id }
              }
            }
            """,
            {"owner": owner, "name": repo},
        )
        owner_node_id = repo_data["repository"]["owner"]["id"]

        project_data = await gh.graphql(
            """
            mutation($ownerId: ID!, $title: String!) {
              createProjectV2(input: {ownerId: $ownerId, title: $title}) {
                projectV2 { id url }
              }
            }
            """,
            {"ownerId": owner_node_id, "title": BOARD_TITLE},
        )
        project_id_node = project_data["createProjectV2"]["projectV2"]["id"]
        board_url = project_data["createProjectV2"]["projectV2"]["url"]

        # Fetch the Status field and update its options
        fields_data = await gh.graphql(
            """
            query($id: ID!) {
              node(id: $id) {
                ... on ProjectV2 {
                  fields(first: 20) {
                    nodes {
                      ... on ProjectV2SingleSelectField {
                        id name
                        options { id name }
                      }
                    }
                  }
                }
              }
            }
            """,
            {"id": project_id_node},
        )
        status_field = next(
            (f for f in fields_data["node"]["fields"]["nodes"] if f.get("name") == "Status"),
            None,
        )
        if status_field:
            column_colors = ["GRAY", "BLUE", "YELLOW", "ORANGE", "GREEN"]
            options = [
                {"name": col, "color": column_colors[i % len(column_colors)], "description": ""}
                for i, col in enumerate(BOARD_COLUMNS)
            ]
            await gh.graphql(
                """
                mutation($input: UpdateProjectV2FieldInput!) {
                  updateProjectV2Field(input: $input) {
                    projectV2Field {
                      ... on ProjectV2SingleSelectField { id name }
                    }
                  }
                }
                """,
                {"input": {
                    "fieldId": status_field["id"],
                    "projectId": project_id_node,
                    "singleSelectField": {"options": options},
                }},
            )

        return BootstrapResourceResult(
            name=BOARD_TITLE,
            status="created",
            detail=board_url,
        )
    except HTTPException as exc:
        return BootstrapResourceResult(name=BOARD_TITLE, status="failed", detail=exc.detail)
    except Exception as exc:
        return BootstrapResourceResult(name=BOARD_TITLE, status="failed", detail=str(exc))


# ── Import wizard — preview ───────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/github/import/preview",
    response_model=ApiResponse[ImportPreviewResponse],
)
async def github_import_preview(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    conn = await _require_connection(project_id, db)
    gh = _get_client(conn)

    issues = await gh.get(
        f"/repos/{conn.repo_owner}/{conn.repo_name}/issues",
        params={"state": "open", "per_page": 100},
    )

    preview = ImportPreviewResponse()
    for issue in issues:
        if issue.get("pull_request"):
            continue
        label_names = [lbl["name"] for lbl in issue.get("labels", [])]
        item = GithubIssuePreview(
            github_issue_number=issue["number"],
            title=issue["title"],
            body=issue.get("body"),
            labels=label_names,
        )
        if "type:epic" in label_names:
            preview.epics.append(item)
        elif "type:feature" in label_names:
            preview.features.append(item)
        elif "type:story" in label_names:
            preview.stories.append(item)
        elif "type:task" in label_names:
            preview.tasks.append(item)
        else:
            preview.unclassified.append(item)

    return ok(preview)


# ── Import wizard — confirm ───────────────────────────────────────────────────

_TYPE_ORDER = {"epic": 0, "feature": 1, "story": 2, "task": 3}


@router.post(
    "/projects/{project_id}/github/import/confirm",
    response_model=ApiResponse[list[ImportedItem]],
    status_code=status.HTTP_201_CREATED,
)
async def github_import_confirm(
    project_id: uuid.UUID,
    body: ImportConfirmRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_project_access(project_id, user, db)
    conn = await _require_connection(project_id, db)
    gh = _get_client(conn)

    # Fetch all issue titles in one request
    raw_issues = await gh.get(
        f"/repos/{conn.repo_owner}/{conn.repo_name}/issues",
        params={"state": "all", "per_page": 100},
    )
    issue_titles: dict[int, str] = {i["number"]: i["title"] for i in raw_issues if not i.get("pull_request")}

    ordered = sorted(body.mappings, key=lambda m: _TYPE_ORDER[m.item_type])

    # issue_number → created ORM object
    created_entities: dict[int, Epic | Feature | Story | Task] = {}
    results: list[ImportedItem] = []

    for mapping in ordered:
        title = mapping.title or issue_titles.get(mapping.github_issue_number, f"Issue #{mapping.github_issue_number}")
        parent_num = mapping.parent_github_issue_number
        parent = created_entities.get(parent_num) if parent_num else None

        if mapping.item_type == "epic":
            await db.execute(select(Project).where(Project.id == project_id).with_for_update())
            count = await db.scalar(select(func.count(Epic.id)).where(Epic.project_id == project_id))
            prefix = f"E{(count or 0) + 1}"
            entity = Epic(project_id=project_id, prefix=prefix, title=title)

        elif mapping.item_type == "feature":
            if not isinstance(parent, Epic):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Issue #{mapping.github_issue_number}: parent issue #{parent_num} is not an epic",
                )
            await db.execute(select(Epic).where(Epic.id == parent.id).with_for_update())
            count = await db.scalar(select(func.count(Feature.id)).where(Feature.epic_id == parent.id))
            prefix = f"{parent.prefix}.F{(count or 0) + 1}"
            entity = Feature(epic_id=parent.id, prefix=prefix, title=title)

        elif mapping.item_type == "story":
            if not isinstance(parent, Feature):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Issue #{mapping.github_issue_number}: parent issue #{parent_num} is not a feature",
                )
            await db.execute(select(Feature).where(Feature.id == parent.id).with_for_update())
            count = await db.scalar(select(func.count(Story.id)).where(Story.feature_id == parent.id))
            prefix = f"{parent.prefix}.S{(count or 0) + 1}"
            entity = Story(feature_id=parent.id, prefix=prefix, title=title)

        else:  # task
            if not isinstance(parent, Story):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Issue #{mapping.github_issue_number}: parent issue #{parent_num} is not a story",
                )
            await db.execute(select(Story).where(Story.id == parent.id).with_for_update())
            count = await db.scalar(select(func.count(Task.id)).where(Task.story_id == parent.id))
            prefix = f"{parent.prefix}.T{(count or 0) + 1}"
            entity = Task(story_id=parent.id, prefix=prefix, title=title)

        db.add(entity)
        await db.flush()
        created_entities[mapping.github_issue_number] = entity
        results.append(ImportedItem(
            github_issue_number=mapping.github_issue_number,
            item_type=mapping.item_type,
            prefix=entity.prefix,
            title=title,
            db_id=entity.id,
        ))

    return created(results)
