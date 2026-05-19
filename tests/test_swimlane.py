"""
Swimlane diagram storage feature tests.

Covers:
- GET /flows/{flow_id} detail — swimlane null on fresh flow, title==name, order==0
- PUT /flows/{flow_id}/swimlane with valid minimal payload → 200, blob echoed with id
- PUT with action.lane_id not in lanes[].id → 422
- PUT with flow.source referencing unknown node id → 422
- GET /flows list items contain title/order but NOT swimlane key
- Full round-trip: PUT with actions/flows, then GET detail verifies persistence
"""
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


def _minimal_swimlane_payload(title: str = "Test Swimlane") -> dict:
    """Minimal valid SwimlaneRequest: 1 lane, initial node, final node, no actions, no flows."""
    return {
        "title": title,
        "lanes": [{"id": "lane-1", "title": "Default Lane"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [],
        "flows": [],
    }


def _full_swimlane_payload() -> dict:
    """Full SwimlaneRequest with actions and flows."""
    return {
        "title": "Full Flow",
        "lanes": [
            {"id": "lane-1", "title": "User"},
            {"id": "lane-2", "title": "System"},
        ],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 50.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-2", "y": 600.0},
        "actions": [
            {
                "id": "action-1",
                "lane_id": "lane-1",
                "label": "User submits form",
                "notation": "action",
                "y": 200.0,
            },
            {
                "id": "action-2",
                "lane_id": "lane-2",
                "label": "System validates",
                "notation": "action",
                "y": 350.0,
                "index": 1,
            },
        ],
        "flows": [
            {"id": "flow-1", "source": "init-1", "target": "action-1"},
            {"id": "flow-2", "source": "action-1", "target": "action-2"},
            {"id": "flow-3", "source": "action-2", "target": "final-1"},
        ],
        "layout": {"zoom": 1.0, "offset": {"x": 0, "y": 0}},
    }


# ── Test cases ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_flow_detail_fresh_swimlane_null(client):
    """GET /flows/{flow_id} on a fresh flow → swimlane is null."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Registration Flow")

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r.status_code == 200, r.text

    data = r.json()["data"]
    assert data["swimlane"] is None


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
async def test_put_swimlane_minimal_valid_returns_200(client):
    """PUT with minimal valid payload → 200, swimlane echoed back."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Payment Flow")
    payload = _minimal_swimlane_payload()

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text

    data = r.json()["data"]
    assert data["swimlane"] is not None


@pytest.mark.asyncio
async def test_put_swimlane_blob_contains_flow_id(client):
    """PUT swimlane → returned swimlane blob has id == str(flow_id)."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)
    payload = _minimal_swimlane_payload()

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text

    swimlane = r.json()["data"]["swimlane"]
    assert swimlane["id"] == flow["id"]


@pytest.mark.asyncio
async def test_put_swimlane_echoes_title_and_lanes(client):
    """PUT swimlane payload is echoed back in the response."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)
    payload = _minimal_swimlane_payload(title="Echo Test")

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text

    swimlane = r.json()["data"]["swimlane"]
    assert swimlane["title"] == "Echo Test"
    assert len(swimlane["lanes"]) == 1
    assert swimlane["lanes"][0]["id"] == "lane-1"


@pytest.mark.asyncio
async def test_put_swimlane_invalid_action_lane_id_returns_422(client):
    """PUT with action.lane_id not in lanes[].id → 422."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    payload = {
        "title": "Bad Lane Ref",
        "lanes": [{"id": "lane-1", "title": "Lane One"}],
        "initial_node": {"id": "init-1", "lane_id": "lane-1", "y": 100.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-1", "y": 500.0},
        "actions": [
            {
                "id": "action-1",
                "lane_id": "lane-NONEXISTENT",  # not in lanes
                "label": "Some action",
                "notation": "action",
                "y": 200.0,
            }
        ],
        "flows": [],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_swimlane_invalid_flow_source_returns_422(client):
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
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_swimlane_invalid_flow_target_returns_422(client):
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
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_list_flows_has_title_and_order_no_swimlane(client):
    """GET /flows list items contain title and order but do NOT have swimlane key."""
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
        assert "swimlane" not in flow_item, "list items must NOT expose 'swimlane'"


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
    """Full round-trip: PUT swimlane with actions and flows, then GET detail verifies persistence."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid, name="Full Flow")
    payload = _full_swimlane_payload()

    # PUT the full payload
    put_r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert put_r.status_code == 200, put_r.text

    # GET the detail endpoint
    get_r = await client.get(
        f"{BASE}/projects/{pid}/flows/{flow['id']}",
        headers=h,
    )
    assert get_r.status_code == 200, get_r.text

    stored = get_r.json()["data"]["swimlane"]
    assert stored is not None, "swimlane should be persisted"

    # Verify structure is preserved
    assert stored["id"] == flow["id"]
    assert stored["title"] == "Full Flow"
    assert len(stored["lanes"]) == 2
    assert len(stored["actions"]) == 2
    assert len(stored["flows"]) == 3

    # Verify action details
    action_ids = {a["id"] for a in stored["actions"]}
    assert "action-1" in action_ids
    assert "action-2" in action_ids

    # Verify flow edge details
    flow_ids = {f["id"] for f in stored["flows"]}
    assert "flow-1" in flow_ids
    assert "flow-2" in flow_ids
    assert "flow-3" in flow_ids

    # Verify layout is stored
    assert stored["layout"] == {"zoom": 1.0, "offset": {"x": 0, "y": 0}}


@pytest.mark.asyncio
async def test_put_swimlane_is_idempotent(client):
    """A second PUT fully replaces the swimlane blob."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    # First PUT
    first_payload = _minimal_swimlane_payload(title="First Version")
    r1 = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=first_payload,
        headers=h,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["swimlane"]["title"] == "First Version"

    # Second PUT with different title
    second_payload = _minimal_swimlane_payload(title="Second Version")
    r2 = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=second_payload,
        headers=h,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["swimlane"]["title"] == "Second Version"

    # GET should return the second version
    r3 = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}", headers=h)
    assert r3.json()["data"]["swimlane"]["title"] == "Second Version"


@pytest.mark.asyncio
async def test_put_swimlane_flow_id_not_found(client):
    """PUT swimlane for a non-existent flow → 404."""
    import uuid
    h, pid = await _setup(client)
    fake_flow_id = str(uuid.uuid4())

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{fake_flow_id}/swimlane",
        json=_minimal_swimlane_payload(),
        headers=h,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_get_flow_detail_wrong_project_returns_404(client):
    """GET /flows/{flow_id} with a flow not belonging to the given project → 404."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    # Create a second project
    org2 = await create_org(client, h)
    proj2 = await create_project(client, h, org2["id"])

    r = await client.get(
        f"{BASE}/projects/{proj2['id']}/flows/{flow['id']}",
        headers=h,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_put_swimlane_missing_required_fields_returns_422(client):
    """PUT swimlane with missing required fields → 422."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    # Missing initial_node and activity_final_node
    incomplete_payload = {
        "title": "Incomplete",
        "lanes": [{"id": "lane-1", "title": "Lane"}],
        # initial_node missing
        # activity_final_node missing
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=incomplete_payload,
        headers=h,
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_swimlane_action_with_valid_lane_id_succeeds(client):
    """PUT with action.lane_id correctly referencing a defined lane → 200."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    payload = {
        "title": "Valid Action Lane",
        "lanes": [
            {"id": "lane-A", "title": "Actor"},
            {"id": "lane-B", "title": "System"},
        ],
        "initial_node": {"id": "init-1", "lane_id": "lane-A", "y": 50.0},
        "activity_final_node": {"id": "final-1", "lane_id": "lane-B", "y": 500.0},
        "actions": [
            {
                "id": "act-1",
                "lane_id": "lane-A",  # valid reference
                "label": "Actor does something",
                "notation": "action",
                "y": 200.0,
            },
            {
                "id": "act-2",
                "lane_id": "lane-B",  # valid reference
                "label": "System responds",
                "notation": "action",
                "y": 350.0,
            },
        ],
        "flows": [
            {"id": "f-1", "source": "init-1", "target": "act-1"},
            {"id": "f-2", "source": "act-1", "target": "act-2"},
            {"id": "f-3", "source": "act-2", "target": "final-1"},
        ],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=payload,
        headers=h,
    )
    assert r.status_code == 200, r.text
    stored = r.json()["data"]["swimlane"]
    assert len(stored["actions"]) == 2
    assert len(stored["flows"]) == 3


@pytest.mark.asyncio
async def test_get_flow_detail_unauthenticated_returns_401_or_403(client):
    """GET /flows/{flow_id} without auth → 401 or 403."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    r = await client.get(f"{BASE}/projects/{pid}/flows/{flow['id']}")
    assert r.status_code in (401, 403), r.text


@pytest.mark.asyncio
async def test_put_swimlane_unauthenticated_returns_401_or_403(client):
    """PUT /flows/{flow_id}/swimlane without auth → 401 or 403."""
    h, pid = await _setup(client)
    flow = await _create_flow(client, h, pid)

    r = await client.put(
        f"{BASE}/projects/{pid}/flows/{flow['id']}/swimlane",
        json=_minimal_swimlane_payload(),
    )
    assert r.status_code in (401, 403), r.text
