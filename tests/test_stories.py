"""
Story endpoints: CRUD, story-builder, close.

Covers:
- POST /projects/{project_id}/story-builder
- POST /projects/{project_id}/features/{feature_id}/user-stories
- GET  /projects/{project_id}/stories  (feature_id + status filters)
- GET  /projects/{project_id}/stories/{user_story_id}
- PATCH /projects/{project_id}/stories/{user_story_id}
- DELETE /projects/{project_id}/stories/{user_story_id}
- PATCH /projects/{project_id}/stories/{user_story_id}/close
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import (
    create_epic,
    create_feature,
    create_org,
    create_project,
    create_story,
    make_auth_headers,
)


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    epic = await create_epic(client, h, proj["id"])
    feature = await create_feature(client, h, proj["id"], epic["id"])
    return h, proj["id"], feature["id"]


# ── Story builder ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_story_builder_creates_story_with_ac(client):
    h, pid, fid = await _setup(client)

    r = await client.post(
        f"{BASE}/projects/{pid}/story-builder",
        json={
            "feature_id": fid,
            "actor_ref": "customer",
            "action_text": "register an account",
            "goal_text": "access the platform",
            "priority": "high",
            "labels": [],
            "acceptance_criteria": [{"description": "Email must be unique", "order": 0}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert "id" in data
    assert data["feature_id"] == fid
    assert len(data["acceptance_criteria"]) == 1


@pytest.mark.asyncio
async def test_create_story_via_feature_endpoint(client):
    h, pid, fid = await _setup(client)

    r = await client.post(
        f"{BASE}/projects/{pid}/features/{fid}/user-stories",
        json={
            "title": "Direct create story",
            "priority": "medium",
            "labels": [],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["feature_id"] == fid


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_stories_returns_created_story(client):
    h, pid, fid = await _setup(client)
    await create_story(client, h, pid, fid)

    r = await client.get(f"{BASE}/projects/{pid}/stories", headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1


@pytest.mark.asyncio
async def test_list_stories_filter_by_feature_id(client):
    h, pid, fid = await _setup(client)
    other_epic = await create_epic(client, h, pid)
    other_feature = await create_feature(client, h, pid, other_epic["id"])
    await create_story(client, h, pid, fid, suffix="-A")
    await create_story(client, h, pid, other_feature["id"], suffix="-B")

    r = await client.get(
        f"{BASE}/projects/{pid}/stories",
        params={"feature_id": fid},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert all(s["feature_id"] == fid for s in data)
    assert len(data) == 1


@pytest.mark.asyncio
async def test_get_story_by_id(client):
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.get(f"{BASE}/projects/{pid}/stories/{story['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["id"] == story["id"]


@pytest.mark.asyncio
async def test_get_story_not_found(client):
    h, pid, _ = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/stories/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_story_description(client):
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/stories/{story['id']}",
        json={"description": "Updated story description"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["description"] == "Updated story description"


@pytest.mark.asyncio
async def test_update_story_terminal_status_via_patch_returns_422(client):
    """Terminal status must go through /close — PATCH with done/rejected must fail."""
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/stories/{story['id']}",
        json={"status": "done"},
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_story_success(client):
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.delete(f"{BASE}/projects/{pid}/stories/{story['id']}", headers=h)
    assert r.status_code == 204

    r2 = await client.get(f"{BASE}/projects/{pid}/stories/{story['id']}", headers=h)
    assert r2.status_code == 404


# ── Close transition ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_story_success(client):
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/stories/{story['id']}/close",
        json={"reason": "done", "comment": "Story delivered"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "done"


@pytest.mark.asyncio
async def test_close_story_wont_fix_reason(client):
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/stories/{story['id']}/close",
        json={"reason": "wont_fix", "comment": "Deprioritized"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "wont_fix"


@pytest.mark.asyncio
async def test_close_story_empty_comment_returns_422(client):
    h, pid, fid = await _setup(client)
    story = await create_story(client, h, pid, fid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/stories/{story['id']}/close",
        json={"reason": "done", "comment": ""},
        headers=h,
    )
    assert r.status_code == 422


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_stories_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/stories", headers=h_other)
    assert r.status_code == 403
