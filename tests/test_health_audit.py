"""
Per-item audit endpoint: GET /projects/{project_id}/requirements/{item_type}/{item_id}/audit
"""
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


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_epic_has_expected_rules(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert {"CLOSE_REASON_REQUIRED", "LABEL_COMPLETE", "TITLE_NO_ACTOR_NAME"}.issubset(rules)
    for c in r.json()["data"]:
        assert isinstance(c["pass"], bool)
        assert isinstance(c["detail"], str)


@pytest.mark.asyncio
async def test_audit_close_reason_passes_for_open_item(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    rule = find_rule(r.json()["data"], "CLOSE_REASON_REQUIRED")
    assert rule["pass"] is True
    assert "not closed" in rule["detail"].lower()


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
async def test_audit_epic_title_no_actor_name_passes_with_no_actors(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid, title="Some Epic Title")

    r = await client.get(f"{BASE}/projects/{pid}/requirements/epic/{epic['id']}/audit", headers=h)
    assert r.status_code == 200
    rule = find_rule(r.json()["data"], "TITLE_NO_ACTOR_NAME")
    assert rule is not None
    assert rule["pass"] is True


@pytest.mark.asyncio
async def test_audit_feature_has_nfr_link_required_not_title_no_actor_name(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert "NFR_LINK_REQUIRED" in rules
    assert "TITLE_NO_ACTOR_NAME" not in rules


@pytest.mark.asyncio
async def test_audit_feature_nfr_link_required_fails_without_nfr(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit", headers=h)
    assert r.status_code == 200
    rule = find_rule(r.json()["data"], "NFR_LINK_REQUIRED")
    assert rule["pass"] is False


@pytest.mark.asyncio
async def test_audit_feature_nfr_link_required_passes_with_linked_nfr(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])

    nfr_r = await client.post(
        f"{BASE}/projects/{pid}/nfrs",
        json={
            "category": "performance",
            "description": "Latency < 100ms",
            "feature_ids": [feature["id"]],
        },
        headers=h,
    )
    assert nfr_r.status_code == 201, nfr_r.text

    r = await client.get(f"{BASE}/projects/{pid}/requirements/feature/{feature['id']}/audit", headers=h)
    assert r.status_code == 200
    assert find_rule(r.json()["data"], "NFR_LINK_REQUIRED")["pass"] is True


@pytest.mark.asyncio
async def test_audit_story_has_acceptance_criteria_required(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])

    r = await client.get(f"{BASE}/projects/{pid}/requirements/story/{story['id']}/audit", headers=h)
    assert r.status_code == 200
    rules = {c["rule"] for c in r.json()["data"]}
    assert {"ACCEPTANCE_CRITERIA_REQUIRED", "CLOSE_REASON_REQUIRED", "LABEL_COMPLETE"}.issubset(rules)
    assert find_rule(r.json()["data"], "ACCEPTANCE_CRITERIA_REQUIRED")["pass"] is True


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
    assert {"CLOSE_REASON_REQUIRED", "LABEL_COMPLETE"}.issubset(rules)
    assert rules.isdisjoint({"TITLE_NO_ACTOR_NAME", "NFR_LINK_REQUIRED", "ACCEPTANCE_CRITERIA_REQUIRED"})


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
async def test_audit_close_reason_fails_for_closed_item_without_reason(client, db_session):
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
    assert find_rule(r.json()["data"], "CLOSE_REASON_REQUIRED")["pass"] is False


@pytest.mark.asyncio
async def test_audit_close_reason_passes_after_proper_close(client):
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
    assert find_rule(r.json()["data"], "CLOSE_REASON_REQUIRED")["pass"] is True
