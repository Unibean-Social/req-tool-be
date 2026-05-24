"""
Context Diagram feature — full CRUD + sync tests.

Covers:
- GET → 404 when no diagram exists, 200 with correct shape after stakeholder added
- POST /stakeholders → 201 + auto-creates diagram; 409 on duplicate; 422 if stakeholder not in project
- DELETE /stakeholders/{id} → 204; cascades all connected flows; 404 if not in diagram
- POST /flows → 201 with generated id; 422 if source/target invalid; 422 if source == target
- PATCH /flows/{id} → 200 updated label; 404 if not found
- DELETE /flows/{id} → 204; 404 if not found
- PUT /layout → 200; layout persisted in next GET
- POST /sync → 404 if no diagram; adds derived flows + stakeholders; no-op on empty project
- Auth → 401 unauthenticated, 403 non-member
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


async def _create_stakeholder(client, h, pid, name="Alice"):
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": name},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _add_to_diagram(client, h, pid, stakeholder_id):
    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders",
        json={"stakeholder_id": stakeholder_id},
        headers=h,
    )
    return r


async def _create_flow_entry(client, h, pid, source, target, label="uses"):
    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/flows",
        json={"source": source, "target": target, "label": label},
        headers=h,
    )
    return r


async def _create_project_flow(client, h, pid, code="FL-01", name="Login Flow"):
    r = await client.post(
        f"{BASE}/projects/{pid}/flows",
        json={"code": code, "name": name, "description": "test flow"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── GET ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_context_diagram_404_when_no_diagram(client):
    h, pid = await _setup(client)
    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_context_diagram_200_after_stakeholder_added(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Customer")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert "center_label" in data
    assert "stakeholders" in data
    assert "flows" in data
    assert len(data["stakeholders"]) == 1
    assert data["stakeholders"][0]["id"] == stakeholder["id"]
    assert data["stakeholders"][0]["name"] == "Customer"


# ── POST /stakeholders ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_stakeholder_creates_diagram_and_returns_201(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Admin")

    r = await _add_to_diagram(client, h, pid, stakeholder["id"])
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["id"] == stakeholder["id"]
    assert data["name"] == "Admin"


@pytest.mark.asyncio
async def test_add_stakeholder_auto_creates_diagram(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Manager")

    # Diagram should not exist yet
    r_before = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_before.status_code == 404

    await _add_to_diagram(client, h, pid, stakeholder["id"])

    # Diagram now exists
    r_after = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_after.status_code == 200


@pytest.mark.asyncio
async def test_add_stakeholder_409_on_duplicate(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Duplicate")

    r1 = await _add_to_diagram(client, h, pid, stakeholder["id"])
    assert r1.status_code == 201

    r2 = await _add_to_diagram(client, h, pid, stakeholder["id"])
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_add_stakeholder_422_if_not_in_project(client):
    h, pid = await _setup(client)

    # Use a random UUID that does not exist as a stakeholder in this project
    random_id = str(uuid.uuid4())
    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders",
        json={"stakeholder_id": random_id},
        headers=h,
    )
    assert r.status_code == 422


# ── DELETE /stakeholders/{id} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_stakeholder_204(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="ToRemove")
    stakeholder2 = await _create_stakeholder(client, h, pid, name="Remaining")
    await _add_to_diagram(client, h, pid, stakeholder["id"])
    await _add_to_diagram(client, h, pid, stakeholder2["id"])

    r = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders/{stakeholder['id']}",
        headers=h,
    )
    assert r.status_code == 204

    # Diagram record persists; only the removed stakeholder is gone
    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    ids_in_diagram = [s["id"] for s in r_get.json()["data"]["stakeholders"]]
    assert stakeholder["id"] not in ids_in_diagram
    assert stakeholder2["id"] in ids_in_diagram


@pytest.mark.asyncio
async def test_remove_stakeholder_cascades_flows(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="CascadeTest")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    # Create flows involving this stakeholder
    sid = stakeholder["id"]
    r1 = await _create_flow_entry(client, h, pid, "center", sid, label="sends to")
    assert r1.status_code == 201
    r2 = await _create_flow_entry(client, h, pid, sid, "center", label="returns to")
    assert r2.status_code == 201

    # Add a second stakeholder so diagram remains accessible after delete
    stakeholder2 = await _create_stakeholder(client, h, pid, name="Keeper")
    await _add_to_diagram(client, h, pid, stakeholder2["id"])

    # Remove first stakeholder
    r_del = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders/{sid}",
        headers=h,
    )
    assert r_del.status_code == 204

    # Flows involving the removed stakeholder should be gone
    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    remaining_flows = r_get.json()["data"]["flows"]
    flow_sources = {f["source"] for f in remaining_flows}
    flow_targets = {f["target"] for f in remaining_flows}
    assert sid not in flow_sources
    assert sid not in flow_targets


@pytest.mark.asyncio
async def test_remove_stakeholder_404_not_in_diagram(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Orphan")

    # Stakeholder exists in project but NOT in diagram
    # First create the diagram by adding a different stakeholder
    other = await _create_stakeholder(client, h, pid, name="OtherBase")
    await _add_to_diagram(client, h, pid, other["id"])

    r = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders/{stakeholder['id']}",
        headers=h,
    )
    assert r.status_code == 404


# ── POST /flows ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_flow_201_with_generated_id(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="EndUser")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    r = await _create_flow_entry(client, h, pid, "center", stakeholder["id"], label="notifies")
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert "id" in data
    assert data["source"] == "center"
    assert data["target"] == stakeholder["id"]
    assert data["label"] == "notifies"


@pytest.mark.asyncio
async def test_create_flow_422_invalid_source(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Ref")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    unknown_id = str(uuid.uuid4())
    r = await _create_flow_entry(client, h, pid, unknown_id, stakeholder["id"], label="x")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_invalid_target(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Ref2")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    unknown_id = str(uuid.uuid4())
    r = await _create_flow_entry(client, h, pid, "center", unknown_id, label="x")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_source_equals_target(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="SelfLoop")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    r = await _create_flow_entry(client, h, pid, "center", "center", label="self")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_stakeholder_source_equals_target(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="SelfRef")
    await _add_to_diagram(client, h, pid, stakeholder["id"])
    sid = stakeholder["id"]

    r = await _create_flow_entry(client, h, pid, sid, sid, label="self-loop")
    assert r.status_code == 422


# ── PATCH /flows/{id} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_flow_label_200(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="UpdateTarget")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    r_create = await _create_flow_entry(client, h, pid, "center", stakeholder["id"], label="original")
    flow_id = r_create.json()["data"]["id"]

    r = await client.patch(
        f"{BASE}/projects/{pid}/context-diagram/flows/{flow_id}",
        json={"label": "updated label"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["label"] == "updated label"
    assert r.json()["data"]["id"] == flow_id


@pytest.mark.asyncio
async def test_update_flow_404_not_found(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="GhostFlowBase")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    ghost_id = str(uuid.uuid4())
    r = await client.patch(
        f"{BASE}/projects/{pid}/context-diagram/flows/{ghost_id}",
        json={"label": "nope"},
        headers=h,
    )
    assert r.status_code == 404


# ── DELETE /flows/{id} ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_flow_204(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="DeleteFlowTarget")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    r_create = await _create_flow_entry(client, h, pid, "center", stakeholder["id"], label="temp")
    flow_id = r_create.json()["data"]["id"]

    r = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/flows/{flow_id}",
        headers=h,
    )
    assert r.status_code == 204

    # Verify flow is gone via GET
    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    flow_ids = [f["id"] for f in r_get.json()["data"]["flows"]]
    assert flow_id not in flow_ids


@pytest.mark.asyncio
async def test_delete_flow_404_not_found(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="FlowDel404")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    ghost_id = str(uuid.uuid4())
    r = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/flows/{ghost_id}",
        headers=h,
    )
    assert r.status_code == 404


# ── PUT /layout ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_layout_200(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="LayoutNode")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    layout_payload = {
        "nodes": [
            {"id": "center", "position": {"x": 400, "y": 300}},
            {"id": stakeholder["id"], "position": {"x": 100, "y": 100}},
        ],
        "edges": [],
    }

    r = await client.put(
        f"{BASE}/projects/{pid}/context-diagram/layout",
        json=layout_payload,
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Layout saved."


@pytest.mark.asyncio
async def test_save_layout_persisted_in_get(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="PersistedNode")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    layout_payload = {
        "nodes": [
            {"id": "center", "position": {"x": 500, "y": 500}},
            {"id": stakeholder["id"], "position": {"x": 200, "y": 200}},
        ],
        "edges": [
            {
                "id": "edge-1",
                "waypoint": None,
                "source_anchor": None,
                "target_anchor": None,
                "label_offset": None,
            }
        ],
    }

    await client.put(
        f"{BASE}/projects/{pid}/context-diagram/layout",
        json=layout_payload,
        headers=h,
    )

    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    layout = r_get.json()["data"]["layout"]
    assert layout is not None
    assert len(layout["nodes"]) == 2
    center_node = next(n for n in layout["nodes"] if n["id"] == "center")
    assert center_node["position"]["x"] == 500
    assert center_node["position"]["y"] == 500


# ── POST /sync ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_404_if_no_diagram(client):
    h, pid = await _setup(client)
    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sync_no_op_when_no_flow_actions(client):
    """Sync on a project with no flow actions adds 0 stakeholders and 0 flows."""
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="InitialNode")
    await _add_to_diagram(client, h, pid, stakeholder["id"])

    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["added_stakeholders"] == 0
    assert data["added_flows"] == 0
    assert "diagram" in data


@pytest.mark.asyncio
async def test_sync_adds_stakeholders_and_flows_from_flow_actions(client):
    """
    When a project has flow actions with actor_id set, sync derives
    stakeholders and flows from those actions.
    """
    h, pid = await _setup(client)

    # Create stakeholder in project (so it can be used as actor)
    actor = await _create_stakeholder(client, h, pid, name="SyncActor")

    # Create a project flow and add an action linked to the actor
    pf = await _create_project_flow(client, h, pid, code="FL-10", name="Sync Test Flow")
    r_action = await client.post(
        f"{BASE}/projects/{pid}/flows/{pf['id']}/actions",
        json=[{"description": "System sends report to user", "order": 1, "actor_id": actor["id"]}],
        headers=h,
    )
    assert r_action.status_code == 201, r_action.text

    # Create the diagram (empty) by adding a placeholder then removing it... or
    # simpler: add actor to diagram first so the diagram exists but actor is already included
    # The test wants the actor NOT in the diagram yet, so we add a dummy stakeholder instead
    dummy = await _create_stakeholder(client, h, pid, name="DiagramAnchor")
    await _add_to_diagram(client, h, pid, dummy["id"])

    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    # The actor should now be added as a new diagram stakeholder
    assert data["added_stakeholders"] == 1
    assert data["added_flows"] >= 1
    actor_ids = [s["id"] for s in data["diagram"]["stakeholders"]]
    assert actor["id"] in actor_ids


@pytest.mark.asyncio
async def test_sync_idempotent_on_second_call(client):
    """Second sync call adds nothing when state is already up-to-date."""
    h, pid = await _setup(client)
    actor = await _create_stakeholder(client, h, pid, name="IdempotentActor")

    pf = await _create_project_flow(client, h, pid, code="FL-20", name="Idempotent Flow")
    await client.post(
        f"{BASE}/projects/{pid}/flows/{pf['id']}/actions",
        json=[{"description": "Actor submits form", "order": 1, "actor_id": actor["id"]}],
        headers=h,
    )

    dummy = await _create_stakeholder(client, h, pid, name="DiagramBase")
    await _add_to_diagram(client, h, pid, dummy["id"])

    # First sync
    r1 = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r1.status_code == 200
    d1 = r1.json()["data"]
    assert d1["added_stakeholders"] == 1

    # Second sync — should add nothing
    r2 = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r2.status_code == 200
    d2 = r2.json()["data"]
    assert d2["added_stakeholders"] == 0
    assert d2["added_flows"] == 0


# ── Auth: 401 unauthenticated, 403 non-member ──────────────────────────────────


@pytest.mark.asyncio
async def test_get_context_diagram_401_unauthenticated(client):
    h, pid = await _setup(client)
    r = await client.get(f"{BASE}/projects/{pid}/context-diagram")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_add_stakeholder_401_unauthenticated(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="SecureTest")
    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders",
        json={"stakeholder_id": stakeholder["id"]},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_context_diagram_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)

    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h_other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_add_stakeholder_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)
    stakeholder = await _create_stakeholder(client, h_owner, pid, name="MemberOnly")

    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/stakeholders",
        json={"stakeholder_id": stakeholder["id"]},
        headers=h_other,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_flow_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)
    stakeholder = await _create_stakeholder(client, h_owner, pid, name="FlowMember")
    await _add_to_diagram(client, h_owner, pid, stakeholder["id"])

    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/flows",
        json={"source": "center", "target": stakeholder["id"], "label": "x"},
        headers=h_other,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sync_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)

    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h_other)
    assert r.status_code == 403
