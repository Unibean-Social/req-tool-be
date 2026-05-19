"""
Project goal endpoints: CRUD.

Covers:
- POST /projects/{project_id}/goals
- GET  /projects/{project_id}/goals
- PATCH /projects/{project_id}/goals/{goal_id}
- DELETE /projects/{project_id}/goals/{goal_id}
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import create_org, create_project, make_auth_headers


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


async def _create_goal(client, h, pid, description="Increase user retention by 20%"):
    r = await client.post(
        f"{BASE}/projects/{pid}/goals",
        json={"description": description},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_goal_success(client):
    h, pid = await _setup(client)
    goal = await _create_goal(client, h, pid, description="Reduce churn rate")

    assert "id" in goal
    assert goal["description"] == "Reduce churn rate"
    assert goal["project_id"] == pid


@pytest.mark.asyncio
async def test_create_goal_missing_description_returns_422(client):
    h, pid = await _setup(client)

    r = await client.post(f"{BASE}/projects/{pid}/goals", json={}, headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_goals_returns_created_goal(client):
    h, pid = await _setup(client)
    await _create_goal(client, h, pid, description="Goal A")

    r = await client.get(f"{BASE}/projects/{pid}/goals", headers=h)
    assert r.status_code == 200
    goals = r.json()["data"]
    assert any(g["description"] == "Goal A" for g in goals)


@pytest.mark.asyncio
async def test_list_goals_empty_project(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/goals", headers=h)
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_update_goal_description(client):
    h, pid = await _setup(client)
    goal = await _create_goal(client, h, pid, description="Original goal")

    r = await client.patch(
        f"{BASE}/projects/{pid}/goals/{goal['id']}",
        json={"description": "Updated goal description"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["description"] == "Updated goal description"


@pytest.mark.asyncio
async def test_update_goal_not_found(client):
    h, pid = await _setup(client)

    r = await client.patch(
        f"{BASE}/projects/{pid}/goals/{uuid.uuid4()}",
        json={"description": "Ghost goal"},
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_goal_success(client):
    h, pid = await _setup(client)
    goal = await _create_goal(client, h, pid)

    r = await client.delete(f"{BASE}/projects/{pid}/goals/{goal['id']}", headers=h)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_goal_not_found(client):
    h, pid = await _setup(client)

    r = await client.delete(f"{BASE}/projects/{pid}/goals/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_goals_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/goals", headers=h_other)
    assert r.status_code == 403
