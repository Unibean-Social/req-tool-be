"""
Business rule endpoints: CRUD.

Covers:
- POST /projects/{project_id}/rules
- GET  /projects/{project_id}/rules
- PATCH /projects/{project_id}/rules/{rule_id}
- DELETE /projects/{project_id}/rules/{rule_id}
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


async def _create_rule(client, h, pid, rule_def="Users must be 18+", rtype="constraint"):
    r = await client.post(
        f"{BASE}/projects/{pid}/rules",
        json={"rule_def": rule_def, "type": rtype},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_rule_constraint_success(client):
    h, pid = await _setup(client)
    rule = await _create_rule(client, h, pid, rule_def="Max 3 retries", rtype="constraint")

    assert "id" in rule
    assert rule["rule_def"] == "Max 3 retries"
    assert rule["type"] == "constraint"
    assert rule["project_id"] == pid


@pytest.mark.asyncio
async def test_create_rule_validation_type(client):
    h, pid = await _setup(client)
    rule = await _create_rule(client, h, pid, rule_def="Email must be valid", rtype="validation")

    assert rule["type"] == "validation"


@pytest.mark.asyncio
async def test_create_rule_policy_type(client):
    h, pid = await _setup(client)
    rule = await _create_rule(client, h, pid, rule_def="All orders require approval", rtype="policy")

    assert rule["type"] == "policy"


@pytest.mark.asyncio
async def test_create_rule_invalid_type_returns_422(client):
    h, pid = await _setup(client)

    r = await client.post(
        f"{BASE}/projects/{pid}/rules",
        json={"rule_def": "Some rule", "type": "unknown_type"},
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_rules_returns_created_rule(client):
    h, pid = await _setup(client)
    await _create_rule(client, h, pid, rule_def="Only admins can delete")

    r = await client.get(f"{BASE}/projects/{pid}/rules", headers=h)
    assert r.status_code == 200
    rules = r.json()["data"]
    assert any(rule["rule_def"] == "Only admins can delete" for rule in rules)


@pytest.mark.asyncio
async def test_list_rules_empty_project(client):
    h, pid = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/rules", headers=h)
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_update_rule_def_and_type(client):
    h, pid = await _setup(client)
    rule = await _create_rule(client, h, pid, rule_def="Old rule", rtype="constraint")

    r = await client.patch(
        f"{BASE}/projects/{pid}/rules/{rule['id']}",
        json={"rule_def": "Updated rule def", "type": "policy"},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["rule_def"] == "Updated rule def"
    assert data["type"] == "policy"


@pytest.mark.asyncio
async def test_update_rule_not_found(client):
    h, pid = await _setup(client)

    r = await client.patch(
        f"{BASE}/projects/{pid}/rules/{uuid.uuid4()}",
        json={"rule_def": "Ghost rule"},
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_rule_success(client):
    h, pid = await _setup(client)
    rule = await _create_rule(client, h, pid)

    r = await client.delete(f"{BASE}/projects/{pid}/rules/{rule['id']}", headers=h)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_rule_not_found(client):
    h, pid = await _setup(client)

    r = await client.delete(f"{BASE}/projects/{pid}/rules/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_rules_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/rules", headers=h_other)
    assert r.status_code == 403
