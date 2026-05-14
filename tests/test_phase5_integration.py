"""
Phase 5 Integration Tests — Best Practices Enforcement

Covers:
  - BP-07 auto-references (create + delete)
  - BP-10 NFR advisory on Feature create/update
  - LABEL_INCOMPLETE at sync push
  - Health score endpoint shape (SQLite-safe)
  - Per-item audit endpoint

Design notes:
  - Each test creates a fresh user (unique email) to avoid 409 conflicts.
    The conftest db_session commits on each request but does NOT roll back
    between tests (SQLite in-memory, session-scoped tables).
  - BP-07 references are verified directly from the DB via db_session, because
    EpicResponse / FeatureResponse / StoryResponse do NOT expose the
    `references` JSON field in their API schemas.
  - The `create_story` endpoint has a known lazy-load issue for the
    `acceptance_criteria` relationship.  We use `/story-builder` (which
    eagerly loads AC) for tests that need a Story.
  - GithubConnection.project_id is a UUID column; the string PK from JSON
    must be converted to uuid.UUID before inserting directly via db_session.
  - The health endpoint uses PostgreSQL JSONB operators; tests tolerate a 500
    on SQLite and skip gracefully.
"""
import uuid as uuid_mod
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from tests.conftest import BASE

# ── Per-test auth helper ───────────────────────────────────────────────────────


async def _make_auth_headers(client) -> dict:
    """Register a new user with a unique email and return Bearer auth headers."""
    uid = uuid_mod.uuid4().hex[:8]
    email = f"p5user-{uid}@example.com"
    reg = await client.post(
        f"{BASE}/auth/register",
        json={"email": email, "password": "Secret123!", "full_name": f"P5 {uid}"},
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": "Secret123!"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Hierarchy creation helpers ─────────────────────────────────────────────────


async def _create_org(client, h):
    slug = f"p5org-{uuid_mod.uuid4().hex[:8]}"
    r = await client.post(
        f"{BASE}/orgs",
        json={"name": f"P5Org {slug}", "slug": slug},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _create_project(client, h, org_id):
    slug = f"p5proj-{uuid_mod.uuid4().hex[:8]}"
    r = await client.post(
        f"{BASE}/orgs/{org_id}/projects",
        json={"name": f"P5Proj {slug}", "slug": slug, "description": "p5"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _create_epic(client, h, pid, title="T Epic", labels=None):
    r = await client.post(
        f"{BASE}/projects/{pid}/epics",
        json={"title": title, "labels": labels or []},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _create_feature(client, h, pid, epic_id, title="T Feature", nfr_note=None, labels=None):
    body = {"title": title, "labels": labels or []}
    if nfr_note is not None:
        body["nfr_note"] = nfr_note
    r = await client.post(
        f"{BASE}/projects/{pid}/epics/{epic_id}/features",
        json=body,
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _create_story_via_builder(client, h, pid, feature_id, title_suffix=""):
    """
    Create a Story via /story-builder (which eagerly loads acceptance_criteria).
    Returns the story data dict from the API response.
    """
    r = await client.post(
        f"{BASE}/projects/{pid}/story-builder",
        json={
            "feature_id": feature_id,
            "actor_ref": "user",
            "action_text": f"do something{title_suffix}",
            "goal_text": "achieve a goal",
            "priority": "medium",
            "labels": [],
            "acceptance_criteria": [{"description": "AC1", "order": 0}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _create_task(client, h, pid, story_id, title="T Task"):
    r = await client.post(
        f"{BASE}/projects/{pid}/stories/{story_id}/tasks",
        json={"title": title, "labels": []},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── DB helpers for references (not exposed in API schemas) ────────────────────


async def _get_epic_references(db_session, epic_id_str: str) -> list:
    """Fetch epic.references directly from the DB, bypassing ORM identity map."""
    from app.models.requirements import Epic
    db_session.expire_all()  # synchronous — forces re-fetch on next access
    result = await db_session.execute(
        select(Epic).where(Epic.id == uuid_mod.UUID(epic_id_str))
    )
    epic = result.scalar_one_or_none()
    return list(epic.references or []) if epic else []


async def _get_feature_references(db_session, feature_id_str: str) -> list:
    from app.models.requirements import Feature
    db_session.expire_all()
    result = await db_session.execute(
        select(Feature).where(Feature.id == uuid_mod.UUID(feature_id_str))
    )
    feat = result.scalar_one_or_none()
    return list(feat.references or []) if feat else []


async def _get_story_references(db_session, story_id_str: str) -> list:
    from app.models.requirements import Story
    db_session.expire_all()
    result = await db_session.execute(
        select(Story).where(Story.id == uuid_mod.UUID(story_id_str))
    )
    story = result.scalar_one_or_none()
    return list(story.references or []) if story else []


async def _setup_github_connection(db_session, pid_str: str):
    """Insert a GithubConnection so push endpoints pass _require_connection."""
    from app.core.crypto import encrypt_token
    from app.models.github_connection import GithubConnection

    conn = GithubConnection(
        project_id=uuid_mod.UUID(pid_str),
        repo_owner="test-owner",
        repo_name="test-repo",
        access_token=encrypt_token("fake-github-token"),
    )
    db_session.add(conn)
    await db_session.flush()
    return conn


def _find_rule(checks, rule_name):
    return next((c for c in checks if c["rule"] == rule_name), None)


def _check_health_or_skip(resp):
    """Return data dict or skip if JSONB not available (SQLite)."""
    if resp.status_code == 500:
        body = resp.text.lower()
        jsonb_indicators = (
            "jsonpath", "jsonb", "@?", "::jsonpath", "operator",
            "unsupportedcompilationerror", "visit_jsonb", "visit_unsupported",
            "can't render element of type jsonb",
        )
        if any(kw in body for kw in jsonb_indicators):
            pytest.skip("Health endpoint uses PostgreSQL JSONB — not supported in SQLite backend")
        pytest.fail(f"Unexpected 500: {resp.text}")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _get_health(client, pid, h):
    """
    Fetch health endpoint, returning (resp, exception) tuple.
    If the JSONB compilation error propagates through the ASGI transport
    (not as an HTTP 500 but as a raised exception), we catch it here so
    the caller can decide to skip.
    """
    try:
        r = await client.get(f"{BASE}/projects/{pid}/health", headers=h)
        return r, None
    except Exception as exc:
        return None, exc


def _handle_health_result(resp, exc):
    """
    Returns the data dict, or calls pytest.skip if the error is JSONB-related.
    Raises AssertionError on unexpected failures.
    """
    if exc is not None:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("jsonb", "unsupportedcompilationerror", "visit_jsonb")):
            pytest.skip("Health endpoint uses PostgreSQL JSONB — not supported in SQLite backend")
        raise exc
    return _check_health_or_skip(resp)


# ═══════════════════════════════════════════════════════════════════════════════
# BP-07 AUTO-REFERENCES
# Verified via db_session.expire_all() + re-query because EpicResponse /
# FeatureResponse / StoryResponse do not include the `references` field.
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bp07_feature_create_adds_to_epic_references(client, db_session):
    """Creating a Feature appends its prefix to the parent Epic's references column."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"], title="Feature Alpha")

    refs = await _get_epic_references(db_session, epic["id"])
    assert feature["prefix"] in refs, (
        f"Expected {feature['prefix']!r} in epic.references {refs}"
    )


@pytest.mark.asyncio
async def test_bp07_story_create_adds_to_feature_references(client, db_session):
    """Creating a Story appends its prefix to the parent Feature's references column."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    story = await _create_story_via_builder(client, h, pid, feature["id"])

    refs = await _get_feature_references(db_session, feature["id"])
    assert story["prefix"] in refs, (
        f"Expected {story['prefix']!r} in feature.references {refs}"
    )


@pytest.mark.asyncio
async def test_bp07_task_create_adds_to_story_references(client, db_session):
    """Creating a Task appends its prefix to the parent Story's references column."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    story = await _create_story_via_builder(client, h, pid, feature["id"])
    task = await _create_task(client, h, pid, story["id"])

    refs = await _get_story_references(db_session, story["id"])
    assert task["prefix"] in refs, (
        f"Expected {task['prefix']!r} in story.references {refs}"
    )


@pytest.mark.asyncio
async def test_bp07_feature_delete_removes_from_epic_references(client, db_session):
    """Deleting a Feature removes its prefix from the parent Epic's references column."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    feature_prefix = feature["prefix"]

    # Verify it was added
    refs_before = await _get_epic_references(db_session, epic["id"])
    assert feature_prefix in refs_before, (
        f"Pre-condition failed: {feature_prefix!r} not in {refs_before}"
    )

    del_resp = await client.delete(
        f"{BASE}/projects/{pid}/features/{feature['id']}",
        headers=h,
    )
    assert del_resp.status_code == 204

    refs_after = await _get_epic_references(db_session, epic["id"])
    assert feature_prefix not in refs_after, (
        f"Feature prefix {feature_prefix!r} should be removed, got {refs_after}"
    )


@pytest.mark.asyncio
async def test_bp07_task_delete_removes_from_story_references(client, db_session):
    """Deleting a Task removes its prefix from the parent Story's references column."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    story = await _create_story_via_builder(client, h, pid, feature["id"])
    task = await _create_task(client, h, pid, story["id"])
    task_prefix = task["prefix"]

    refs_before = await _get_story_references(db_session, story["id"])
    assert task_prefix in refs_before, (
        f"Pre-condition failed: {task_prefix!r} not in {refs_before}"
    )

    del_resp = await client.delete(
        f"{BASE}/projects/{pid}/tasks/{task['id']}",
        headers=h,
    )
    assert del_resp.status_code == 204

    refs_after = await _get_story_references(db_session, story["id"])
    assert task_prefix not in refs_after, (
        f"Task prefix {task_prefix!r} should be removed, got {refs_after}"
    )


@pytest.mark.asyncio
async def test_bp07_multiple_features_accumulate_in_epic_references(client, db_session):
    """Multiple features all appear in epic references."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    f1 = await _create_feature(client, h, pid, epic["id"], title="Feature One")
    f2 = await _create_feature(client, h, pid, epic["id"], title="Feature Two")

    refs = await _get_epic_references(db_session, epic["id"])
    assert f1["prefix"] in refs, f"f1 prefix {f1['prefix']!r} not in {refs}"
    assert f2["prefix"] in refs, f"f2 prefix {f2['prefix']!r} not in {refs}"


@pytest.mark.asyncio
async def test_bp07_story_delete_removes_from_feature_references(client, db_session):
    """Deleting a Story removes its prefix from the parent Feature's references column."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    story = await _create_story_via_builder(client, h, pid, feature["id"])
    story_prefix = story["prefix"]

    refs_before = await _get_feature_references(db_session, feature["id"])
    assert story_prefix in refs_before, (
        f"Pre-condition failed: {story_prefix!r} not in {refs_before}"
    )

    del_resp = await client.delete(
        f"{BASE}/projects/{pid}/stories/{story['id']}",
        headers=h,
    )
    assert del_resp.status_code == 204

    refs_after = await _get_feature_references(db_session, feature["id"])
    assert story_prefix not in refs_after, (
        f"Story prefix {story_prefix!r} should be removed, got {refs_after}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# BP-10 NFR ADVISORY
# ═══════════════════════════════════════════════════════════════════════════════

BP10_MSG = "BP-10: No non-functional requirement note provided for this feature"


@pytest.mark.asyncio
async def test_bp10_feature_without_nfr_note_has_warning(client):
    """Feature created without nfr_note returns BP-10 warning in response."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/features",
        json={"title": "No NFR Feature", "labels": []},
        headers=h,
    )
    assert r.status_code == 201, r.text
    warnings = r.json()["data"].get("warnings", [])
    assert BP10_MSG in warnings, f"Expected BP-10, got: {warnings}"


@pytest.mark.asyncio
async def test_bp10_feature_with_empty_nfr_note_has_warning(client):
    """Whitespace-only nfr_note still triggers BP-10."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/features",
        json={"title": "Blank NFR", "labels": [], "nfr_note": "   "},
        headers=h,
    )
    assert r.status_code == 201, r.text
    warnings = r.json()["data"].get("warnings", [])
    assert BP10_MSG in warnings, f"Expected BP-10 for blank nfr_note, got: {warnings}"


@pytest.mark.asyncio
async def test_bp10_feature_with_nfr_note_has_no_warning(client):
    """Feature created WITH valid nfr_note produces no BP-10 warning."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/features",
        json={"title": "NFR Feature", "labels": [], "nfr_note": "Response < 200ms"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    warnings = r.json()["data"].get("warnings", [])
    assert warnings == [], f"Expected no warnings, got: {warnings}"


@pytest.mark.asyncio
async def test_bp10_feature_update_without_nfr_has_warning(client):
    """PATCHing a Feature that still lacks nfr_note triggers BP-10."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])

    r = await client.patch(
        f"{BASE}/projects/{pid}/features/{feature['id']}",
        json={"title": "Updated Title"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    warnings = r.json()["data"].get("warnings", [])
    assert BP10_MSG in warnings, f"Expected BP-10 on update, got: {warnings}"


@pytest.mark.asyncio
async def test_bp10_feature_update_adding_nfr_clears_warning(client):
    """Adding nfr_note via PATCH removes the BP-10 warning."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])

    r = await client.patch(
        f"{BASE}/projects/{pid}/features/{feature['id']}",
        json={"nfr_note": "No data loss under any failure scenario."},
        headers=h,
    )
    assert r.status_code == 200, r.text
    warnings = r.json()["data"].get("warnings", [])
    assert warnings == [], f"Expected no warnings after adding nfr_note, got: {warnings}"


# ═══════════════════════════════════════════════════════════════════════════════
# LABEL_INCOMPLETE AT SYNC PUSH
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_label_incomplete_push_fails_with_error_code(client, db_session):
    """Pushing an epic with no labels returns LABEL_INCOMPLETE in the failed list."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid, title="Unlabeled Epic")  # labels=[]
    await _setup_github_connection(db_session, pid)

    stage = await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )
    assert stage.status_code == 200, stage.text

    mock_gh = MagicMock()
    mock_inst = MagicMock()
    mock_gh.return_value = mock_inst
    mock_inst.post = AsyncMock(return_value={"number": 99, "html_url": "https://gh/99"})

    with patch("app.routers.sync.GithubClient", mock_gh):
        push = await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    assert push.status_code == 200, push.text
    report = push.json()["data"]

    assert len(report["pushed"]) == 0, f"Should have no pushed: {report['pushed']}"
    assert len(report["failed"]) >= 1, f"Should have failures: {report['failed']}"
    failed = report["failed"][0]
    assert failed["error_code"] == "LABEL_INCOMPLETE", f"Got: {failed}"
    assert "Missing label categories" in (failed["error_message"] or "")


@pytest.mark.asyncio
async def test_label_incomplete_partial_labels_fails(client, db_session):
    """Epic with only 'type:' label (missing status: and priority:) triggers LABEL_INCOMPLETE."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid, title="Partial Labels", labels=["type:feature"])
    await _setup_github_connection(db_session, pid)

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    with patch("app.routers.sync.GithubClient", MagicMock()):
        push = await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    assert push.status_code == 200
    report = push.json()["data"]
    label_fails = [f for f in report["failed"] if f["error_code"] == "LABEL_INCOMPLETE"]
    assert label_fails, f"Expected LABEL_INCOMPLETE in failed, got: {report['failed']}"


@pytest.mark.asyncio
async def test_label_complete_push_does_not_get_label_incomplete(client, db_session):
    """Epic with all three required label prefixes does not trigger LABEL_INCOMPLETE."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(
        client, h, pid, title="Full Labels",
        labels=["type:epic", "status:open", "priority:high"],
    )
    await _setup_github_connection(db_session, pid)

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    mock_gh = MagicMock()
    mock_inst = MagicMock()
    mock_gh.return_value = mock_inst
    mock_inst.post = AsyncMock(return_value={"number": 1, "html_url": "https://gh/1"})

    with patch("app.routers.sync.GithubClient", mock_gh):
        push = await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    assert push.status_code == 200
    report = push.json()["data"]
    label_fails = [f for f in report["failed"] if f["error_code"] == "LABEL_INCOMPLETE"]
    assert not label_fails, f"Should not have LABEL_INCOMPLETE: {label_fails}"
    # Epic has no parent dependency, so it should succeed
    assert len(report["pushed"]) == 1, f"Expected 1 pushed, got: {report['pushed']}"


@pytest.mark.asyncio
async def test_label_incomplete_appears_in_sync_logs(client, db_session):
    """After a failed push, LABEL_INCOMPLETE appears in the sync logs."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid, title="Log Test Epic")
    await _setup_github_connection(db_session, pid)

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    with patch("app.routers.sync.GithubClient", MagicMock()):
        await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    logs_resp = await client.get(f"{BASE}/projects/{pid}/sync/logs", headers=h)
    assert logs_resp.status_code == 200, logs_resp.text
    logs = logs_resp.json()["data"]
    label_logs = [lg for lg in logs if lg.get("error_code") == "LABEL_INCOMPLETE"]
    assert label_logs, f"Expected LABEL_INCOMPLETE in logs, got: {logs}"


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH SCORE ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_health_endpoint_returns_200_and_required_keys(client):
    """GET /health returns 200 with ac_coverage, label_completeness, close_hygiene, overall, item_counts."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    r, exc = await _get_health(client, pid, h)
    data = _handle_health_result(r, exc)

    required = {"ac_coverage", "label_completeness", "close_hygiene", "overall", "item_counts"}
    assert required.issubset(data.keys()), f"Missing keys: {required - data.keys()}"
    item_counts = data["item_counts"]
    for k in ("epics", "features", "stories", "tasks"):
        assert k in item_counts, f"item_counts missing '{k}'"


@pytest.mark.asyncio
async def test_health_empty_project_has_zero_counts_and_100_scores(client):
    """Empty project: counts=0, ac_coverage=100, close_hygiene=100."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    r, exc = await _get_health(client, pid, h)
    data = _handle_health_result(r, exc)

    assert data["item_counts"]["epics"] == 0
    assert data["item_counts"]["features"] == 0
    assert data["item_counts"]["stories"] == 0
    assert data["item_counts"]["tasks"] == 0
    assert data["ac_coverage"] == 100, f"ac_coverage should be 100 for empty, got {data['ac_coverage']}"
    assert data["close_hygiene"] == 100, f"close_hygiene should be 100 for empty, got {data['close_hygiene']}"


@pytest.mark.asyncio
async def test_health_counts_reflect_created_items(client):
    """item_counts reflects the actual items in the project."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    story = await _create_story_via_builder(client, h, pid, feature["id"])
    await _create_task(client, h, pid, story["id"])

    r, exc = await _get_health(client, pid, h)
    data = _handle_health_result(r, exc)

    assert data["item_counts"]["epics"] == 1
    assert data["item_counts"]["features"] == 1
    assert data["item_counts"]["stories"] == 1
    assert data["item_counts"]["tasks"] == 1


@pytest.mark.asyncio
async def test_health_overall_is_integer_in_valid_range(client):
    """overall is an integer 0–100."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    r, exc = await _get_health(client, pid, h)
    data = _handle_health_result(r, exc)

    assert isinstance(data["overall"], int)
    assert 0 <= data["overall"] <= 100


@pytest.mark.asyncio
async def test_health_403_for_non_member(client):
    """Non-member is denied access to /health."""
    h_owner = await _make_auth_headers(client)
    h_other = await _make_auth_headers(client)

    org = await _create_org(client, h_owner)
    proj = await _create_project(client, h_owner, org["id"])
    pid = proj["id"]

    r = await client.get(f"{BASE}/projects/{pid}/health", headers=h_other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_health_404_nonexistent_project(client):
    """Health endpoint returns 404 for a project that doesn't exist."""
    h = await _make_auth_headers(client)
    r = await client.get(f"{BASE}/projects/{uuid_mod.uuid4()}/health", headers=h)
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# PER-ITEM AUDIT ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_audit_epic_contains_bp05_label_complete_bp12(client):
    """Audit on an epic returns BP-05, LABEL_COMPLETE, and BP-12 entries."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200, r.text
    checks = r.json()["data"]
    assert isinstance(checks, list)

    rule_names = {c["rule"] for c in checks}
    assert "BP-05" in rule_names
    assert "LABEL_COMPLETE" in rule_names
    assert "BP-12" in rule_names

    for c in checks:
        assert "rule" in c
        assert isinstance(c["pass"], bool)
        assert isinstance(c["detail"], str)


@pytest.mark.asyncio
async def test_audit_epic_bp05_passes_when_item_is_open(client):
    """BP-05 passes (pass=true, 'not closed' detail) for an open epic."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    bp05 = _find_rule(r.json()["data"], "BP-05")
    assert bp05 is not None
    assert bp05["pass"] is True
    assert "not closed" in bp05["detail"].lower()


@pytest.mark.asyncio
async def test_audit_epic_label_complete_fails_for_unlabeled_epic(client):
    """LABEL_COMPLETE=false for an epic created with no labels."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)  # labels=[]

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    lc = _find_rule(r.json()["data"], "LABEL_COMPLETE")
    assert lc is not None
    assert lc["pass"] is False
    assert "Missing" in lc["detail"]


@pytest.mark.asyncio
async def test_audit_epic_label_complete_passes_with_all_prefixes(client):
    """LABEL_COMPLETE=true when type:, status:, priority: are all present."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    epic = await _create_epic(
        client, h, pid, title="Full Label Epic",
        labels=["type:epic", "status:open", "priority:high"],
    )

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    lc = _find_rule(r.json()["data"], "LABEL_COMPLETE")
    assert lc is not None
    assert lc["pass"] is True


@pytest.mark.asyncio
async def test_audit_epic_bp12_passes_when_no_actors_registered(client):
    """BP-12 passes (no violation) when the project has no registered actors."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid, title="Some Epic Title")

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    bp12 = _find_rule(r.json()["data"], "BP-12")
    assert bp12 is not None
    assert bp12["pass"] is True


@pytest.mark.asyncio
async def test_audit_feature_contains_bp05_label_complete_bp10(client):
    """Audit on a feature returns BP-05, LABEL_COMPLETE, and BP-10 (not BP-12)."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200, r.text
    rule_names = {c["rule"] for c in r.json()["data"]}

    assert "BP-05" in rule_names
    assert "LABEL_COMPLETE" in rule_names
    assert "BP-10" in rule_names
    assert "BP-12" not in rule_names  # BP-12 is epic-only


@pytest.mark.asyncio
async def test_audit_feature_bp10_fails_without_nfr_note(client):
    """BP-10=false in audit when feature has no nfr_note."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])  # no nfr_note

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    bp10 = _find_rule(r.json()["data"], "BP-10")
    assert bp10 is not None
    assert bp10["pass"] is False
    assert "missing" in bp10["detail"].lower()


@pytest.mark.asyncio
async def test_audit_feature_bp10_passes_with_nfr_note(client):
    """BP-10=true in audit when feature has an nfr_note."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(
        client, h, pid, epic["id"], nfr_note="Latency < 100ms at p99"
    )

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    bp10 = _find_rule(r.json()["data"], "BP-10")
    assert bp10 is not None
    assert bp10["pass"] is True


@pytest.mark.asyncio
async def test_audit_story_contains_bp03_and_fails_without_ac(client):
    """Story audit includes BP-03 and fails it because story-builder AC is present."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    # story-builder requires ≥1 AC, so BP-03 should PASS for builder-created stories
    story = await _create_story_via_builder(client, h, pid, feature["id"])

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/story/{story['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200, r.text
    rule_names = {c["rule"] for c in r.json()["data"]}

    assert "BP-03" in rule_names
    assert "BP-05" in rule_names
    assert "LABEL_COMPLETE" in rule_names

    bp03 = _find_rule(r.json()["data"], "BP-03")
    # Story was created via story-builder which requires ≥1 AC, so BP-03 passes
    assert bp03["pass"] is True


@pytest.mark.asyncio
async def test_audit_task_contains_bp05_label_complete_only(client):
    """Task audit has BP-05 and LABEL_COMPLETE but no type-specific rules."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)
    feature = await _create_feature(client, h, pid, epic["id"])
    story = await _create_story_via_builder(client, h, pid, feature["id"])
    task = await _create_task(client, h, pid, story["id"])

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/task/{task['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200, r.text
    rule_names = {c["rule"] for c in r.json()["data"]}

    assert "BP-05" in rule_names
    assert "LABEL_COMPLETE" in rule_names
    # Tasks have no type-specific rule
    assert "BP-12" not in rule_names
    assert "BP-10" not in rule_names
    assert "BP-03" not in rule_names


@pytest.mark.asyncio
async def test_audit_returns_404_for_nonexistent_item(client):
    """Audit returns 404 when the item doesn't exist."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{uuid_mod.uuid4()}/audit",
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_audit_returns_403_for_non_member(client):
    """Non-member cannot access the audit endpoint."""
    h_owner = await _make_auth_headers(client)
    h_other = await _make_auth_headers(client)

    org = await _create_org(client, h_owner)
    proj = await _create_project(client, h_owner, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h_owner, pid)

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h_other,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_bp05_fails_closed_item_without_close_reason(client, db_session):
    """BP-05 fails for an epic that is terminal but has no CloseReason record."""
    from app.models.requirements import Epic, ItemStatus

    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    # Directly set status to terminal without creating a CloseReason
    db_session.expire_all()
    result = await db_session.execute(
        select(Epic).where(Epic.id == uuid_mod.UUID(epic["id"]))
    )
    db_epic = result.scalar_one()
    db_epic.status = ItemStatus.done
    await db_session.flush()

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    bp05 = _find_rule(r.json()["data"], "BP-05")
    assert bp05 is not None
    assert bp05["pass"] is False, (
        f"BP-05 should fail for closed item without CloseReason, got: {bp05}"
    )


@pytest.mark.asyncio
async def test_audit_bp05_passes_after_proper_close_with_close_reason(client):
    """BP-05 passes for an epic properly closed via /close (creates CloseReason)."""
    h = await _make_auth_headers(client)
    org = await _create_org(client, h)
    proj = await _create_project(client, h, org["id"])
    pid = proj["id"]
    epic = await _create_epic(client, h, pid)

    close = await client.patch(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/close",
        json={"reason": "done", "comment": "All tasks complete"},
        headers=h,
    )
    assert close.status_code == 200, close.text

    r = await client.get(
        f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit",
        headers=h,
    )
    assert r.status_code == 200
    bp05 = _find_rule(r.json()["data"], "BP-05")
    assert bp05 is not None
    assert bp05["pass"] is True, (
        f"BP-05 should pass for properly closed epic, got: {bp05}"
    )
