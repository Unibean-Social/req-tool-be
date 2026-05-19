"""
Epic endpoints: CRUD, close, requirements tree.

Covers:
- POST /projects/{project_id}/actors/{actor_id}/epics
- GET  /projects/{project_id}/epics  (limit/offset pagination)
- GET  /projects/{project_id}/epics/{epic_id}
- PATCH /projects/{project_id}/epics/{epic_id}
- DELETE /projects/{project_id}/epics/{epic_id}
- PATCH /projects/{project_id}/epics/{epic_id}/close
- GET  /projects/{project_id}/requirements/tree
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import (
    create_actor,
    create_epic,
    create_org,
    create_project,
    make_auth_headers,
)


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_epic_success(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid, title="User Registration")

    assert epic["title"] == "User Registration"
    assert "id" in epic
    assert epic["status"] == "draft"


@pytest.mark.asyncio
async def test_list_epics_returns_created_epic(client):
    h, pid = await _setup(client)
    await create_epic(client, h, pid, title="Epic A")

    r = await client.get(f"{BASE}/projects/{pid}/epics", headers=h)
    assert r.status_code == 200
    epics = r.json()["data"]
    assert len(epics) >= 1
    assert any(e["title"] == "Epic A" for e in epics)


@pytest.mark.asyncio
async def test_list_epics_empty_project(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/epics", headers=h)
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_list_epics_pagination_limit(client):
    h, pid = await _setup(client)
    actor = await create_actor(client, h, pid)
    for i in range(5):
        await create_epic(client, h, pid, actor_id=actor["id"], title=f"Epic {i}")

    r = await client.get(f"{BASE}/projects/{pid}/epics", params={"limit": 2, "offset": 0}, headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


@pytest.mark.asyncio
async def test_list_epics_pagination_offset(client):
    h, pid = await _setup(client)
    actor = await create_actor(client, h, pid)
    for i in range(4):
        await create_epic(client, h, pid, actor_id=actor["id"], title=f"Epic {i}")

    r_all = await client.get(f"{BASE}/projects/{pid}/epics", params={"limit": 100}, headers=h)
    r_page2 = await client.get(f"{BASE}/projects/{pid}/epics", params={"limit": 2, "offset": 2}, headers=h)
    assert r_page2.status_code == 200
    assert len(r_page2.json()["data"]) == 2
    # Titles in page2 must not overlap with page1
    titles_all = [e["title"] for e in r_all.json()["data"]]
    titles_p2 = [e["title"] for e in r_page2.json()["data"]]
    assert titles_p2 == titles_all[2:4]


@pytest.mark.asyncio
async def test_get_epic_by_id(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid, title="Find Me")

    r = await client.get(f"{BASE}/projects/{pid}/epics/{epic['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Find Me"


@pytest.mark.asyncio
async def test_get_epic_not_found(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/epics/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_epic_title_and_description(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid, title="Old Title")

    r = await client.patch(
        f"{BASE}/projects/{pid}/epics/{epic['id']}",
        json={"title": "New Title", "description": "Updated desc"},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["title"] == "New Title"
    assert data["description"] == "Updated desc"


@pytest.mark.asyncio
async def test_update_epic_not_found(client):
    h, pid = await _setup(client)

    r = await client.patch(
        f"{BASE}/projects/{pid}/epics/{uuid.uuid4()}",
        json={"title": "Ghost"},
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_epic_success(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.delete(f"{BASE}/projects/{pid}/epics/{epic['id']}", headers=h)
    assert r.status_code == 204

    r2 = await client.get(f"{BASE}/projects/{pid}/epics/{epic['id']}", headers=h)
    assert r2.status_code == 404


# ── Close transition ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_epic_success(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/close",
        json={"reason": "done", "comment": "Completed successfully"},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["reason"] == "done"
    assert data["comment"] == "Completed successfully"


@pytest.mark.asyncio
async def test_close_epic_rejected_reason(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/close",
        json={"reason": "rejected", "comment": "Out of scope"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "rejected"


@pytest.mark.asyncio
async def test_close_epic_missing_comment_returns_422(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/epics/{epic['id']}/close",
        json={"reason": "done", "comment": ""},
        headers=h,
    )
    assert r.status_code == 422


# ── Requirements tree ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requirements_tree_returns_list(client):
    h, pid = await _setup(client)
    await create_epic(client, h, pid, title="Tree Epic")

    r = await client.get(f"{BASE}/projects/{pid}/requirements/tree", headers=h)
    assert r.status_code == 200
    tree = r.json()["data"]
    assert isinstance(tree, list)
    assert any(e["title"] == "Tree Epic" for e in tree)


@pytest.mark.asyncio
async def test_requirements_tree_empty_project(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/requirements/tree", headers=h)
    assert r.status_code == 200
    assert r.json()["data"] == []


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_epics_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/epics", headers=h_other)
    assert r.status_code == 403
