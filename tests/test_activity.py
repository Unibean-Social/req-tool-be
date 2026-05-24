"""
activity diagram storage feature tests.

Covers:
- GET /flows/{flow_id} detail — activity null on fresh flow with no actions, title==name, order==0
- POST /flows/{flow_id}/actions — activity auto-generated with correct structure
- PUT /flows/{flow_id}/canvas-layout with valid minimal payload → 200, blob echoed with id
- PUT with action.lane_id not in lanes[].id → 422
- PUT with action.id not in flow's ProjectFlowAction → 422
- PUT with flow.source referencing unknown node id → 422
- GET /flows list items contain title/order but NOT activity key
- Full round-trip: PUT with actions/flows (using real action IDs), then GET detail verifies
  label auto-populated from ProjectFlowAction.description
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import create_org, create_project, make_auth_headers


# ── Fixtures / helpers ─────────────────────────────────────────────────────────


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


async def _create_flow(client, h, pid, code="FL-01", name="My Flow"):
    r = await client.post(
        f"{BASE}/projects/{pid}/flows",
        json={"code": code, "name": name},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _create_action(client, h, pid, flow_id, description="Actor does something.", order=0):
    r = await client.post(
        f"{BASE}/projects/{pid}/flows/{flow_id}/actions",
        json=[{"order": order, "description": description}],
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"][0]


def _minimal_activity_payload(title: str = "Test activity") -> dict:
    """Minimal valid activityRequest: 1 lane, initial node, final node, no actions, no flows."""
    return {
        "title": title,
        "lanes": [{"id": "lane-1", "title": "Default Lane"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [],
        "flows": [],
    }


# ── Test cases ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_flow_detail_fresh_activity_null(client):
    """GET /flows/{flow_id} on a fresh flow → activity is null."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Registration Flow")

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r.status_code == 200, r.text

    data = r.json()["data"]
    assert data["activity"] is None


@pytest.mark.asyncio
async def test_activity_auto_generated_after_create_actions(client):
    """POST /actions auto-generates activity; GET detail returns non-null activity."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Payment Flow")

    await _create_action(client, h, pid, flow["id"], description="User submits payment form.", order=0)
    await _create_action(client, h, pid, flow["id"], description="Validate card details.", order=1)

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r.status_code == 200, r.text
    sw = r.json()["data"]["activity"]

    assert sw is not None
    assert sw["id"] == flow["id"]
    assert sw["title"] == "Payment Flow"
    assert len(sw["lanes"]) >= 1
    assert sw["initial_node"]["id"] == "start"
    assert sw["activity_final_node"]["id"] == "end"
    assert len(sw["actions"]) == 2
    for act in sw["actions"]:
        if act["notation"] in ("action", "objectNode"):
            assert act["label"] not in (None, ""), f"action node missing label: {act}"
    assert len(sw["flows"]) >= 3


@pytest.mark.asyncio
async def test_get_flow_detail_title_equals_name(client):
    """GET /flows/{flow_id} — title computed field equals name."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Checkout Flow")

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r.status_code == 200, r.text

    data = r.json()["data"]
    assert data["title"] == "Checkout Flow"
    assert data["title"] == data["name"]


@pytest.mark.asyncio
async def test_get_flow_detail_order_is_zero(client):
    """GET /flows/{flow_id} — order defaults to 0."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r.status_code == 200, r.text

    data = r.json()["data"]
    assert data["order"] == 0


@pytest.mark.asyncio
async def test_put_activity_minimal_valid_returns_200(client):
    """PUT with minimal valid payload (no actions) → 200, activity echoed back."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Payment Flow")
    payload = _minimal_activity_payload()

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text

    data = r.json()["data"]
    assert data["activity"] is not None


@pytest.mark.asyncio
async def test_put_activity_blob_contains_flow_id(client):
    """PUT activity → returned activity blob has id == str(flow_id)."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)
    payload = _minimal_activity_payload()

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text

    activity = r.json()["data"]["activity"]
    assert activity["id"] == flow["id"]


@pytest.mark.asyncio
async def test_put_activity_echoes_title_and_lanes(client):
    """PUT activity payload is echoed back in the response."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)
    payload = _minimal_activity_payload(title="Echo Test")

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text

    activity = r.json()["data"]["activity"]
    assert activity["title"] == "Echo Test"
    assert len(activity["lanes"]) == 1
    assert activity["lanes"][0]["id"] == "lane-1"


@pytest.mark.asyncio
async def test_put_activity_invalid_action_lane_id_returns_422(client):
    """PUT with action.lane_id not in lanes[].id → 422 from Pydantic validator."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)
    action = await _create_action(client, h, pid, flow["id"])

    payload = {
        "title": "Bad Lane Ref",
        "lanes": [{"id": "lane-1", "title": "Lane One"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [
            {
                "id": action["id"],
                "lane_id": "lane-NONEXISTENT",  # not in lanes
                "notation": "action",
                "y": 200.0,
            }
        ],
        "flows": [],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_activity_action_id_not_in_flow_returns_422(client):
    """PUT with action.id that is a valid UUID but not in this flow's actions → 422."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    payload = {
        "title": "Unknown Action",
        "lanes": [{"id": "lane-1", "title": "Lane One"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [
            {
                "id": str(uuid.uuid4()),  # valid UUID but not in this flow
                "lane_id": "lane-1",
                "notation": "action",
                "y": 200.0,
            }
        ],
        "flows": [],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_activity_invalid_flow_source_returns_422(client):
    """PUT with flow.source referencing unknown node id → 422."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    payload = {
        "title": "Bad Source Ref",
        "lanes": [{"id": "lane-1", "title": "Lane One"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [],
        "flows": [
            {
                "id": "edge-1",
                "source": "GHOST-NODE",  # not a known node id
                "target": "final-1",
            }
        ],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_activity_invalid_flow_target_returns_422(client):
    """PUT with flow.target referencing unknown node id → 422."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    payload = {
        "title": "Bad Target Ref",
        "lanes": [{"id": "lane-1", "title": "Lane One"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [],
        "flows": [
            {
                "id": "edge-1",
                "source": "init-1",
                "target": "GHOST-TARGET",  # not a known node id
            }
        ],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_list_flows_has_title_and_order_no_activity(client):
    """GET /flows list items contain title and order but do NOT have activity key."""
    h, pid = await _setup(client)
    await _create_flow(client, h, pid, code="FL-01", name="Flow Alpha")
    await _create_flow(client, h, pid, code="FL-02", name="Flow Beta")

    r = await client.get(f"{BASE}/projects/{pid}/flows", headers=h)
    assert r.status_code == 200, r.text

    flows = r.json()["data"]
    assert len(flows) == 2
    for flow_item in flows:
        assert "title" in flow_item, "list items must have 'title'"
        assert "order" in flow_item, "list items must have 'order'"
        assert "activity" not in flow_item, "list items must NOT expose 'activity'"


@pytest.mark.asyncio
async def test_list_flows_title_matches_name(client):
    """GET /flows list — title equals name for each item."""
    h, pid = await _setup(client)
    await _create_flow(client, h, pid, code="FL-01", name="Onboarding Flow")

    r = await client.get(f"{BASE}/projects/{pid}/flows", headers=h)
    assert r.status_code == 200, r.text

    flows = r.json()["data"]
    assert flows[0]["title"] == "Onboarding Flow"
    assert flows[0]["title"] == flows[0]["name"]


@pytest.mark.asyncio
async def test_full_round_trip_put_then_get(client):
    """Full round-trip: PUT activity using real action IDs → GET detail verifies
    persistence and that label is auto-populated from ProjectFlowAction.description."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Full Flow")

    act1 = await _create_action(client, h, pid, flow["id"], description="User submits form.", order=0)
    act2 = await _create_action(client, h, pid, flow["id"], description="System validates.", order=1)

    payload = {
        "title": "Full Flow",
        "lanes": [
            {"id": "lane-1", "title": "User"},
            {"id": "lane-2", "title": "System"},
        ],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 50.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-2", "y": 600.0},
        "actions": [
            {"id": act1["id"], "lane_id": "lane-1", "notation": "action", "y": 200.0},
            {"id": act2["id"], "lane_id": "lane-2", "notation": "action", "y": 350.0, "index": 1},
        ],
        "flows": [
            {"id": "flow-1", "source": "init-1", "target": act1["id"]},
            {"id": "flow-2", "source": act1["id"], "target": act2["id"]},
            {"id": "flow-3", "source": act2["id"], "target": "final-1"},
        ],
        "layout": {"zoom": 1.0, "offset": {"x": 0, "y": 0}},
    }

    put_r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert put_r.status_code == 200, put_r.text

    get_r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert get_r.status_code == 200, get_r.text

    stored = get_r.json()["data"]["activity"]
    assert stored is not None
    assert stored["id"] == flow["id"]
    assert stored["title"] == "Full Flow"
    assert len(stored["lanes"]) == 2
    assert len(stored["actions"]) == 2
    assert len(stored["flows"]) == 3

    # Labels auto-populated from ProjectFlowAction.description
    action_map = {a["id"]: a for a in stored["actions"]}
    assert action_map[act1["id"]]["label"] == "User submits form."
    assert action_map[act2["id"]]["label"] == "System validates."

    # Layout preserved
    assert stored["layout"] == {"zoom": 1.0, "offset": {"x": 0, "y": 0}}


@pytest.mark.asyncio
async def test_put_activity_is_idempotent(client):
    """A second PUT fully replaces the activity blob."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    first_payload = _minimal_activity_payload(title="First Version")
    r1 = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=first_payload,
        headers=h,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["activity"]["title"] == "First Version"

    second_payload = _minimal_activity_payload(title="Second Version")
    r2 = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=second_payload,
        headers=h,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["activity"]["title"] == "Second Version"

    r3 = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r3.json()["data"]["activity"]["title"] == "Second Version"


@pytest.mark.asyncio
async def test_put_activity_flow_id_not_found(client):
    """PUT activity for a non-existent flow → 404."""
    h, pid = await _setup(client)
    fake_flow_id = str(uuid.uuid4())

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{fake_flow_id}/canvas-layout",
        json=_minimal_activity_payload(),
        headers=h,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_get_flow_detail_wrong_project_returns_404(client):
    """GET /flows/{flow_id} with a flow not belonging to the given project → 404."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    org2 = await create_org(client, h)
    proj2 = await create_project(client, h, org2["id"])

    r = await client.get(
        f"{BASE}/projects/{proj2['id']}/flows/{flow['id']}",
        headers=h,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_put_activity_missing_required_fields_returns_422(client):
    """PUT activity with missing required fields → 422."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    incomplete_payload = {
        "title": "Incomplete",
        "lanes": [{"id": "lane-1", "title": "Lane"}],
        # initial_node and activity_final_node missing
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=incomplete_payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_activity_action_with_valid_lane_id_succeeds(client):
    """PUT with real action IDs and valid lane references → 200, labels populated."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)
    act1 = await _create_action(client, h, pid, flow["id"], description="Actor does something.", order=0)
    act2 = await _create_action(client, h, pid, flow["id"], description="System responds.", order=1)

    payload = {
        "title": "Valid Action Lane",
        "lanes": [
            {"id": "lane-A", "title": "Actor"},
            {"id": "lane-B", "title": "System"},
        ],
        "initial_node": {"id": "init-1", "lane_id": "lane-A", "y": 50.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-B", "y": 500.0},
        "actions": [
            {"id": act1["id"], "lane_id": "lane-A", "notation": "action", "y": 200.0},
            {"id": act2["id"], "lane_id": "lane-B", "notation": "action", "y": 350.0},
        ],
        "flows": [
            {"id": "f-1", "source": "init-1", "target": act1["id"]},
            {"id": "f-2", "source": act1["id"], "target": act2["id"]},
            {"id": "f-3", "source": act2["id"], "target": "final-1"},
        ],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text
    stored = r.json()["data"]["activity"]
    assert len(stored["actions"]) == 2
    assert len(stored["flows"]) == 3
    # Labels auto-populated
    labels = {a["id"]: a["label"] for a in stored["actions"]}
    assert labels[act1["id"]] == "Actor does something."
    assert labels[act2["id"]] == "System responds."


@pytest.mark.asyncio
async def test_get_flow_detail_unauthenticated_returns_401_or_403(client):
    """GET /flows/{flow_id} without auth → 401 or 403."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}")
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_put_activity_unauthenticated_returns_401_or_403(client):
    """PUT /flows/{flow_id}/canvas-layout without auth → 401 or 403."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/canvas-layout",
        json=_minimal_activity_payload(),
    )
    assert r.status_code in (401, 403), r.text
