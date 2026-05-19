"""
ProjectFlowAction CRUD, rule-linking, and is_business_actor flag.

Covers:
- Flow creation with code/name fields (no title/order)
- FlowAction CRUD (create, update, delete)
- FlowAction rule-linking (add / remove)
- Cascading deletes (flow → actions → junction rows)
- is_business_actor flag on Stakeholder
- actor_id linkage on FlowAction
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import create_org, create_project, make_auth_headers


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


async def create_flow(client, h, pid, code="FL-01", name="Registration Flow"):
    r = await client.post(
        f"{BASE}/projects/{pid}/flows",
        json={"code": code, "name": name, "description": "A test flow"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_rule(client, h, pid, rule_def="Users must be 18+", rtype="constraint"):
    r = await client.post(
        f"{BASE}/projects/{pid}/rules",
        json={"rule_def": rule_def, "type": rtype},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_stakeholder(client, h, pid, name="Alice", is_business_actor=False):
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": name, "is_business_actor": is_business_actor},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── Flow CRUD (code/name fields) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_flow_with_code_and_name(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid, code="FL-01", name="Login Flow")

    assert flow["code"] == "FL-01"
    assert flow["name"] == "Login Flow"
    assert flow["actions"] == []
    assert "id" in flow
    assert "project_id" in flow


@pytest.mark.asyncio
async def test_list_flows_returns_code_name_and_actions(client):
    h, pid = await _setup(client)
    await create_flow(client, h, pid, code="FL-01", name="Flow One")
    await create_flow(client, h, pid, code="FL-02", name="Flow Two")

    r = await client.get(f"{BASE}/projects/{pid}/flows", headers=h)
    assert r.status_code == 200
    flows = r.json()["data"]
    assert len(flows) == 2
    codes = {f["code"] for f in flows}
    assert {"FL-01", "FL-02"} == codes
    for f in flows:
        assert "actions" in f


@pytest.mark.asyncio
async def test_update_flow_code_and_name(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/flows/{flow['id']}",
        json={"code": "FL-99", "name": "Updated Name"},
        headers=h,
    )
    assert r.status_code == 200
    updated = r.json()["data"]
    assert updated["code"] == "FL-99"
    assert updated["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_flow_response_has_no_title_field(client):
    """Ensure the old 'title' field is gone."""
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    assert "title" not in flow


# ── FlowAction CRUD ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_flow_action_minimal(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Student selects course", "order": 1},
        headers=h,
    )
    assert r.status_code == 201, r.text
    action = r.json()["data"]
    assert action["description"] == "Student selects course."
    assert action["order"] == 1
    assert action["actor_id"] is None
    assert action["rules"] == []
    assert action["flow_id"] == flow["id"]


@pytest.mark.asyncio
async def test_create_flow_action_with_actor(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    stakeholder = await create_stakeholder(client, h, pid, name="System", is_business_actor=True)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "System validates payment", "order": 2, "actor_id": stakeholder["id"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    action = r.json()["data"]
    assert action["actor_id"] == stakeholder["id"]


@pytest.mark.asyncio
async def test_update_flow_action_description_and_order(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    # Create action
    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Original description", "order": 1},
        headers=h,
    )
    action = r.json()["data"]

    # Update it
    r = await client.patch(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}",
        json={"description": "Updated description", "order": 5},
        headers=h,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["data"]
    assert updated["description"] == "Updated description."
    assert updated["order"] == 5


@pytest.mark.asyncio
async def test_delete_flow_action(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Temp action", "order": 0},
        headers=h,
    )
    action = r.json()["data"]

    r = await client.delete(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}",
        headers=h,
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_update_flow_action_404_unknown(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    r = await client.patch(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{uuid.uuid4()}",
        json={"description": "Ghost action"},
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_flow_action_404_unknown(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    r = await client.delete(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{uuid.uuid4()}",
        headers=h,
    )
    assert r.status_code == 404


# ── Rule-link endpoints ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_rule_to_action(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    rule = await create_rule(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Validate input", "order": 1},
        headers=h,
    )
    action = r.json()["data"]

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}/rules/{rule['id']}",
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    rule_ids = [rx["id"] for rx in data["rules"]]
    assert rule["id"] in rule_ids


@pytest.mark.asyncio
async def test_add_rule_to_action_idempotent(client):
    """Adding the same rule twice should not create duplicates."""
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    rule = await create_rule(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "User action", "order": 0},
        headers=h,
    )
    action = r.json()["data"]
    url = f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}/rules/{rule['id']}"

    await client.post(url, headers=h)
    r2 = await client.post(url, headers=h)
    assert r2.status_code == 200
    assert len(r2.json()["data"]["rules"]) == 1


@pytest.mark.asyncio
async def test_remove_rule_from_action(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    rule = await create_rule(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "User action", "order": 0},
        headers=h,
    )
    action = r.json()["data"]

    # Link the rule
    await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}/rules/{rule['id']}",
        headers=h,
    )

    # Remove it
    r = await client.delete(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}/rules/{rule['id']}",
        headers=h,
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_add_rule_unknown_action_404(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    rule = await create_rule(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{uuid.uuid4()}/rules/{rule['id']}",
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_add_unknown_rule_to_action_404(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "User action", "order": 0},
        headers=h,
    )
    action = r.json()["data"]

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}/rules/{uuid.uuid4()}",
        headers=h,
    )
    assert r.status_code == 404


# ── Cascade deletes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_flow_cascades_to_actions(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    # Create two actions
    for i in range(2):
        await client.post(
            f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
            json={"description": f"Action {i}", "order": i},
            headers=h,
        )

    # Delete the flow
    r = await client.delete(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r.status_code == 204

    # Listing flows should return empty
    r = await client.get(f"{BASE}/projects/{pid}/flows", headers=h)
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_list_flows_includes_nested_actions(client):
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)

    await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Step 1", "order": 1},
        headers=h,
    )
    await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Step 2", "order": 2},
        headers=h,
    )

    r = await client.get(f"{BASE}/projects/{pid}/flows", headers=h)
    flows = r.json()["data"]
    assert len(flows) == 1
    actions = flows[0]["actions"]
    assert len(actions) == 2
    # Actions should be ordered by order field
    assert actions[0]["order"] == 1
    assert actions[1]["order"] == 2


# ── is_business_actor on Stakeholder ──────────────────────────────────────────


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
    stakeholder = await create_stakeholder(client, h, pid, name="Alice")
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
    stakeholder = await create_stakeholder(client, h, pid, name="Bob", is_business_actor=True)

    r = await client.get(
        f"{BASE}/projects/{pid}/stakeholders/{stakeholder['id']}",
        headers=h,
    )
    assert r.status_code == 200
    assert "is_business_actor" in r.json()["data"]
    assert r.json()["data"]["is_business_actor"] is True


# ── actor_id on FlowAction ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flow_action_with_business_actor_stakeholder(client):
    """FlowAction actor_id should link to a business-actor stakeholder."""
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    ba = await create_stakeholder(client, h, pid, name="Finance Dept", is_business_actor=True)

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Finance approves budget", "order": 3, "actor_id": ba["id"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    action = r.json()["data"]
    assert action["actor_id"] == ba["id"]


@pytest.mark.asyncio
async def test_list_flows_actions_include_rules(client):
    """GET /flows should return actions with their nested rules."""
    h, pid = await _setup(client)
    flow = await create_flow(client, h, pid)
    rule = await create_rule(client, h, pid, rule_def="Payment must be verified")

    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions",
        json={"description": "Process payment", "order": 1},
        headers=h,
    )
    action = r.json()["data"]

    await client.post(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/actions/{action['id']}/rules/{rule['id']}",
        headers=h,
    )

    r = await client.get(f"{BASE}/projects/{pid}/flows", headers=h)
    flows = r.json()["data"]
    nested_actions = flows[0]["actions"]
    assert len(nested_actions) == 1
    nested_rules = nested_actions[0]["rules"]
    assert len(nested_rules) == 1
    assert nested_rules[0]["id"] == rule["id"]
