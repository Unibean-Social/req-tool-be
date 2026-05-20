"""
Project setup endpoints: setup-progress and staleness-warnings.

Covers:
- GET /projects/{project_id}/setup-progress
- GET /projects/{project_id}/staleness-warnings
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


# ── Setup progress ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_setup_progress_returns_required_keys(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/setup-progress", headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert "core" in data
    assert "business_requirements" in data
    assert "user_requirements" in data
    assert "functional_requirements" in data


@pytest.mark.asyncio
async def test_setup_progress_empty_project_all_false(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/setup-progress", headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    br = data["business_requirements"]
    assert br["stakeholders"] is False
    assert br["goals"] is False
    assert br["flows"] is False
    assert br["rules"] is False
    assert data["user_requirements"]["nfrs"] is False
    assert data["functional_requirements"]["actors"] is False


@pytest.mark.asyncio
async def test_setup_progress_reflects_added_goal(client):
    h, pid = await _setup(client)
    await client.post(
        f"{BASE}/projects/{pid}/goals",
        json={"description": "Increase revenue"},
        headers=h,
    )

    r = await client.get(f"{BASE}/projects/{pid}/setup-progress", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["business_requirements"]["goals"] is True


@pytest.mark.asyncio
async def test_setup_progress_reflects_added_rule(client):
    h, pid = await _setup(client)
    await client.post(
        f"{BASE}/projects/{pid}/rules",
        json={"rule_def": "Admin only", "type": "constraint"},
        headers=h,
    )

    r = await client.get(f"{BASE}/projects/{pid}/setup-progress", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["business_requirements"]["rules"] is True


@pytest.mark.asyncio
async def test_setup_progress_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/setup-progress", headers=h_other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_setup_progress_unknown_project_returns_404(client):
    h = await make_auth_headers(client)

    r = await client.get(f"{BASE}/projects/{uuid.uuid4()}/setup-progress", headers=h)
    assert r.status_code == 404


# ── Staleness warnings ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_staleness_warnings_empty_project_returns_empty_list(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/staleness-warnings", headers=h)
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_staleness_warnings_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/staleness-warnings", headers=h_other)
    assert r.status_code == 403
