"""
Stakeholder CRUD and actor_type / system_description fields.

Covers:
- Create stakeholder (default actor_type, explicit actor_type)
- Update actor_type and system_description (including null-clear)
- GET single stakeholder response shape
- List with actor_type filter and no filter
"""
import pytest

from tests.conftest import BASE
from tests.helpers import create_org, create_project, make_auth_headers


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


async def _create_stakeholder(client, h, pid, name="Alice", actor_type=None):
    body = {"name": name}
    if actor_type is not None:
        body["actor_type"] = actor_type
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json=body,
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_stakeholder_default_actor_type(client):
    h, pid = await _setup(client)
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": "Regular User"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["actor_type"] == "none"


@pytest.mark.asyncio
async def test_create_stakeholder_with_actor_type(client):
    h, pid = await _setup(client)
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": "Business Owner", "actor_type": "business_actor"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["actor_type"] == "business_actor"


@pytest.mark.asyncio
async def test_update_stakeholder_actor_type(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Alice")
    assert stakeholder["actor_type"] == "none"

    r = await client.patch(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        json={"actor_type": "other_actor"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["actor_type"] == "other_actor"


@pytest.mark.asyncio
async def test_stakeholder_response_includes_actor_type(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Bob", actor_type="business_actor")

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "actor_type" in data
    assert data["actor_type"] == "business_actor"


@pytest.mark.asyncio
async def test_list_stakeholders_no_filter_returns_all(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Regular")
    await _create_stakeholder(client, h, pid, name="BizActor", actor_type="business_actor")

    r = await client.get(f"{BASE}/projects/{pid}/stakeholders", headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


@pytest.mark.asyncio
async def test_list_stakeholders_filter_single_actor_type(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Regular")
    await _create_stakeholder(client, h, pid, name="BizActor", actor_type="business_actor")

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders",
        params={"actor_type": "business_actor"},
        headers=h,
    )
    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 1
    assert items[0]["actor_type"] == "business_actor"


@pytest.mark.asyncio
async def test_list_stakeholders_filter_multiple_actor_types(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Regular")
    await _create_stakeholder(client, h, pid, name="BizActor", actor_type="business_actor")
    await _create_stakeholder(client, h, pid, name="ExtSystem", actor_type="other_actor")

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders",
        params=[("actor_type", "business_actor"), ("actor_type", "other_actor")],
        headers=h,
    )
    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"BizActor", "ExtSystem"}


@pytest.mark.asyncio
async def test_update_stakeholder_system_description(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Carol")

    r = await client.patch(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        json={"system_description": "Handles billing workflows"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["system_description"] == "Handles billing workflows"


@pytest.mark.asyncio
async def test_update_stakeholder_clear_system_description(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Dave")

    await client.patch(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        json={"system_description": "Initial description"},
        headers=h,
    )

    r = await client.patch(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        json={"system_description": None},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["system_description"] is None
