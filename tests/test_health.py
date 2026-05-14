"""Tests for project health score and per-item audit endpoints."""
import uuid

import pytest
from sqlalchemy import select

from tests.conftest import BASE
from tests.helpers import (
    create_epic,
    create_feature,
    create_org,
    create_project,
    create_story,
    create_task,
    find_rule,
    make_auth_headers,
)


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


def _skip_if_jsonb_unavailable(resp, exc):
    """Return data dict or pytest.skip if the error is JSONB on SQLite."""
    if exc is not None:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("jsonb", "unsupportedcompilationerror", "visit_jsonb")):
            pytest.skip("JSONB not available on SQLite")
        raise exc
    if resp.status_code == 500:
        body = resp.text.lower()
        if any(kw in body for kw in ("jsonpath", "jsonb", "@?", "operator", "visit_jsonb")):
            pytest.skip("JSONB not available on SQLite")
        pytest.fail(f"Unexpected 500: {resp.text}")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _get_health(client, pid, h):
    try:
        r = await client.get(f"{BASE}/projects/{pid}/health", headers=h)
        return r, None
    except Exception as exc:
        return None, exc


# ── Health score ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_returns_required_keys(client):
    h, pid = await _setup(client)
    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert {"ac_coverage", "label_completeness", "close_hygiene", "overall", "item_counts"}.issubset(data)
    for k in ("epics", "features", "stories", "tasks"):
        assert k in data["item_counts"]


@pytest.mark.asyncio
async def test_health_empty_project_defaults_to_100(client):
    h, pid = await _setup(client)
    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert data["item_counts"] == {"epics": 0, "features": 0, "stories": 0, "tasks": 0}
    assert data["ac_coverage"] == 100
    assert data["close_hygiene"] == 100


@pytest.mark.asyncio
async def test_health_item_counts_reflect_created_items(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])
    await create_task(client, h, pid, story["id"])

    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert data["item_counts"] == {"epics": 1, "features": 1, "stories": 1, "tasks": 1}


@pytest.mark.asyncio
async def test_health_overall_is_int_in_range(client):
    h, pid = await _setup(client)
    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert isinstance(data["overall"], int)
    assert 0 <= data["overall"] <= 100


@pytest.mark.asyncio
async def test_health_403_for_non_member(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/health", headers=h_other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_health_404_unknown_project(client):
    h = await make_auth_headers(client)
    r = await client.get(f"{BASE}/projects/{uuid.uuid4()}/health", headers=h)
    assert r.status_code == 404


# ── Per-item audit ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_epic_has_bp05_label_complete_bp12(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert {"BP-05", "LABEL_COMPLETE", "BP-12"}.issubset(rules)
    for c in r.json()["data"]:
        assert isinstance(c["pass"], bool)
        assert isinstance(c["detail"], str)


@pytest.mark.asyncio
async def test_audit_bp05_passes_for_open_item(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    bp05 = find_rule(r.json()["data"], "BP-05")
    assert bp05["pass"] is True
    assert "not closed" in bp05["detail"].lower()


@pytest.mark.asyncio
async def test_audit_label_complete_fails_for_unlabeled_item(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    lc = find_rule(r.json()["data"], "LABEL_COMPLETE")
    assert lc["pass"] is False
    assert "Missing" in lc["detail"]


@pytest.mark.asyncio
async def test_audit_label_complete_passes_with_all_prefixes(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid, labels=["type:epic", "status:open", "priority:high"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    assert find_rule(r.json()["data"], "LABEL_COMPLETE")["pass"] is True


@pytest.mark.asyncio
async def test_audit_epic_bp12_passes_with_no_actors(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid, title="Some Epic Title")

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    bp12 = find_rule(r.json()["data"], "BP-12")
    assert bp12 is not None
    assert bp12["pass"] is True


@pytest.mark.asyncio
async def test_audit_feature_has_bp10_not_bp12(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert "BP-10" in rules
    assert "BP-12" not in rules


@pytest.mark.asyncio
async def test_audit_feature_bp10_fails_without_nfr_note(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit", headers=h)
    assert r.status_code == 200
    bp10 = find_rule(r.json()["data"], "BP-10")
    assert bp10["pass"] is False


@pytest.mark.asyncio
async def test_audit_feature_bp10_passes_with_nfr_note(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"], nfr_note="Latency < 100ms")

    r = await client.get(f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit", headers=h)
    assert r.status_code == 200
    assert find_rule(r.json()["data"], "BP-10")["pass"] is True


@pytest.mark.asyncio
async def test_audit_story_has_bp03_passes_when_ac_present(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/story/{story['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert {"BP-03", "BP-05", "LABEL_COMPLETE"}.issubset(rules)
    assert find_rule(r.json()["data"], "BP-03")["pass"] is True


@pytest.mark.asyncio
async def test_audit_task_has_only_universal_rules(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])
    task = await create_task(client, h, pid, story["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/task/{task['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert {"BP-05", "LABEL_COMPLETE"}.issubset(rules)
    assert rules.isdisjoint({"BP-12", "BP-10", "BP-03"})


@pytest.mark.asyncio
async def test_audit_404_unknown_item(client):
    h, pid = await _setup(client)
    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{uuid.uuid4()}/audit", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_audit_403_non_member(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])
    epic = await create_epic(client, h_owner, proj["id"])

    r = await client.get(
        f"{BASE}/projects/{proj['id']}/requirements/epic/{epic['id']}/audit",
        headers=h_other,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_bp05_fails_closed_item_without_close_reason(client, db_session):
    from app.models.requirements import Epic, ItemStatus

    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    db_session.expire_all()
    result = await db_session.execute(select(Epic).where(Epic.id == uuid.UUID(epic["id"])))
    db_epic = result.scalar_one()
    db_epic.status = ItemStatus.done
    await db_session.flush()

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    assert find_rule(r.json()["data"], "BP-05")["pass"] is False


@pytest.mark.asyncio
async def test_audit_bp05_passes_after_proper_close(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/close",
        json={"reason": "done", "comment": "Complete"},
        headers=h,
    )
    assert r.status_code == 200

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    assert find_rule(r.json()["data"], "BP-05")["pass"] is True
