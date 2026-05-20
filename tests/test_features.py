"""
Feature endpoints: CRUD, close, list filters.

Covers:
- POST /projects/{project_id}/epics/{epic_id}/features
- GET  /projects/{project_id}/features  (epic_id + status filters)
- GET  /projects/{project_id}/features/{feature_id}
- PATCH /projects/{project_id}/features/{feature_id}
- DELETE /projects/{project_id}/features/{feature_id}
- PATCH /projects/{project_id}/features/{feature_id}/close
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import (
    create_epic,
    create_feature,
    create_org,
    create_project,
    make_auth_headers,
)


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    epic = await create_epic(client, h, proj["id"])
    return h, proj["id"], epic["id"]


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_feature_success(client):
    h, pid, epic_id = await _setup(client)
    feature = await create_feature(client, h, pid, epic_id, title="Login Module")

    assert feature["title"] == "Login Module"
    assert "id" in feature
    assert feature["status"] == "draft"
    assert feature["epic_id"] == epic_id


@pytest.mark.asyncio
async def test_list_features_returns_created_feature(client):
    h, pid, epic_id = await _setup(client)
    await create_feature(client, h, pid, epic_id, title="Feature A")

    r = await client.get(f"{BASE}/projects/{pid}/features", headers=h)
    assert r.status_code == 200
    features = r.json()["data"]
    assert any(f["title"] == "Feature A" for f in features)


@pytest.mark.asyncio
async def test_list_features_filter_by_epic_id(client):
    h, pid, epic_id = await _setup(client)
    other_epic = await create_epic(client, h, pid)
    await create_feature(client, h, pid, epic_id, title="In Epic A")
    await create_feature(client, h, pid, other_epic["id"], title="In Other Epic")

    r = await client.get(
        f"{BASE}/projects/{pid}/features",
        params={"epic_id": epic_id},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert all(f["epic_id"] == epic_id for f in data)
    assert len(data) == 1
    assert data[0]["title"] == "In Epic A"


@pytest.mark.asyncio
async def test_get_feature_by_id(client):
    h, pid, epic_id = await _setup(client)
    feature = await create_feature(client, h, pid, epic_id, title="Find Me")

    r = await client.get(f"{BASE}/projects/{pid}/features/{feature['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Find Me"


@pytest.mark.asyncio
async def test_get_feature_not_found(client):
    h, pid, _ = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/features/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_feature_title(client):
    h, pid, epic_id = await _setup(client)
    feature = await create_feature(client, h, pid, epic_id, title="Old Title")

    r = await client.patch(
        f"{BASE}/projects/{pid}/features/{feature['id']}",
        json={"title": "Updated Feature Title"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Updated Feature Title"


@pytest.mark.asyncio
async def test_delete_feature_success(client):
    h, pid, epic_id = await _setup(client)
    feature = await create_feature(client, h, pid, epic_id)

    r = await client.delete(f"{BASE}/projects/{pid}/features/{feature['id']}", headers=h)
    assert r.status_code == 204

    r2 = await client.get(f"{BASE}/projects/{pid}/features/{feature['id']}", headers=h)
    assert r2.status_code == 404


# ── Close transition ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_feature_success(client):
    h, pid, epic_id = await _setup(client)
    feature = await create_feature(client, h, pid, epic_id)

    r = await client.patch(
        f"{BASE}/projects/{pid}/features/{feature['id']}/close",
        json={"reason": "done", "comment": "Feature complete"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "done"


@pytest.mark.asyncio
async def test_close_feature_empty_comment_returns_422(client):
    h, pid, epic_id = await _setup(client)
    feature = await create_feature(client, h, pid, epic_id)

    r = await client.patch(
        f"{BASE}/projects/{pid}/features/{feature['id']}/close",
        json={"reason": "done", "comment": ""},
        headers=h,
    )
    assert r.status_code == 422


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_features_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/features", headers=h_other)
    assert r.status_code == 403
