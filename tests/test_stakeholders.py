"""
Stakeholder CRUD and is_business_actor flag.

Covers:
- Create stakeholder (default + explicit is_business_actor)
- Update is_business_actor
- GET single stakeholder response shape
- List with is_business_actor filter (true / false / no filter)
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


async def _create_stakeholder(client, h, pid, name="Alice", is_business_actor=False):
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": name, "is_business_actor": is_business_actor},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_stakeholder_default_not_business_actor(client):
    h, pid = await _setup(client)
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": "Regular User"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["is_business_actor"] is False


@pytest.mark.asyncio
async def test_create_stakeholder_as_business_actor(client):
    h, pid = await _setup(client)
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": "Business Owner", "is_business_actor": True},
        headers=h,
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["is_business_actor"] is True


@pytest.mark.asyncio
async def test_update_stakeholder_is_business_actor(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Alice")
    assert stakeholder["is_business_actor"] is False

    r = await client.patch(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        json={"is_business_actor": True},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_business_actor"] is True


@pytest.mark.asyncio
async def test_stakeholder_response_includes_is_business_actor(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Bob", is_business_actor=True)

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        headers=h,
    )
    assert r.status_code == 200
    assert "is_business_actor" in r.json()["data"]
    assert r.json()["data"]["is_business_actor"] is True


@pytest.mark.asyncio
async def test_list_stakeholders_no_filter_returns_all(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Regular", is_business_actor=False)
    await _create_stakeholder(client, h, pid, name="BizActor", is_business_actor=True)

    r = await client.get(f"{BASE}/projects/{pid}/stakeholders", headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 2


@pytest.mark.asyncio
async def test_list_stakeholders_filter_true_returns_only_business_actors(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Regular", is_business_actor=False)
    await _create_stakeholder(client, h, pid, name="BizActor", is_business_actor=True)

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders",
        params={"is_business_actor": "true"},
        headers=h,
    )
    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 1
    assert items[0]["is_business_actor"] is True
    assert items[0]["name"] == "BizActor"


@pytest.mark.asyncio
async def test_list_stakeholders_filter_false_returns_only_non_business_actors(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Regular", is_business_actor=False)
    await _create_stakeholder(client, h, pid, name="BizActor", is_business_actor=True)

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders",
        params={"is_business_actor": "false"},
        headers=h,
    )
    assert r.status_code == 200
    items = r.json()["data"]
    assert len(items) == 1
    assert items[0]["is_business_actor"] is False
    assert items[0]["name"] == "Regular"
