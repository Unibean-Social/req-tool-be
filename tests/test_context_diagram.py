"""
Context Diagram feature tests.

Stakeholders auto-sync to the diagram when created with actor_type=business_actor|other_actor.
Stakeholders auto-removed (with cascade flows) when deleted.

Covers:
- GET → 404 when no diagram, 200 after business_actor stakeholder created
- Auto-add: business_actor and other_actor stakeholders appear in diagram on create
- Auto-skip: actor_type=none stakeholder does NOT appear in diagram
- Auto-remove: deleting a stakeholder removes it + cascades flows from diagram
- POST /flows → 201; 422 if source/target invalid or equal; 422 if both endpoints non-center
- PATCH /flows/{id} → 200; 404 if not found
- DELETE /flows/{id} → 204; 404 if not found
- PUT /layout → 200; persisted in next GET
- POST /sync → 404 if no diagram; adds derived flows + stakeholders; idempotent on 2nd call
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


async def _create_stakeholder(client, h, pid, name="Alice", actor_type="business_actor"):
    r = await client.post(
        f"{BASE}/projects/{pid}/stakeholders",
        json={"name": name, "actor_type": actor_type},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


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
async def test_get_context_diagram_200_after_business_actor_created(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="Customer", actor_type="business_actor")

    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert "center_label" in data
    assert len(data["stakeholders"]) == 1
    assert data["stakeholders"][0]["id"] == stakeholder["id"]
    assert data["stakeholders"][0]["name"] == "Customer"


# ── Auto-sync: stakeholder create ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_business_actor_auto_added_to_diagram(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="BizActor", actor_type="business_actor")

    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["data"]["stakeholders"]]
    assert stakeholder["id"] in ids


@pytest.mark.asyncio
async def test_other_actor_auto_added_to_diagram(client):
    h, pid = await _setup(client)
    stakeholder = await _create_stakeholder(client, h, pid, name="OtherActor", actor_type="other_actor")

    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["data"]["stakeholders"]]
    assert stakeholder["id"] in ids


@pytest.mark.asyncio
async def test_none_actor_not_added_to_diagram(client):
    h, pid = await _setup(client)
    # First create a business_actor to ensure diagram exists
    await _create_stakeholder(client, h, pid, name="Base", actor_type="business_actor")

    # none actor should NOT be in the diagram
    none_stakeholder = await _create_stakeholder(client, h, pid, name="Spectator", actor_type="none")

    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["data"]["stakeholders"]]
    assert none_stakeholder["id"] not in ids


@pytest.mark.asyncio
async def test_auto_creates_diagram_on_first_actor(client):
    h, pid = await _setup(client)

    r_before = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_before.status_code == 404

    await _create_stakeholder(client, h, pid, name="First", actor_type="business_actor")

    r_after = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_after.status_code == 200


# ── Auto-sync: stakeholder delete ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_stakeholder_removes_from_diagram(client):
    h, pid = await _setup(client)
    s1 = await _create_stakeholder(client, h, pid, name="ToRemove", actor_type="business_actor")
    s2 = await _create_stakeholder(client, h, pid, name="Remaining", actor_type="business_actor")

    r = await client.delete(f"{BASE}/projects/{pid}/stakeholders/{s1['id']}", headers=h)
    assert r.status_code == 204

    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    ids = [s["id"] for s in r_get.json()["data"]["stakeholders"]]
    assert s1["id"] not in ids
    assert s2["id"] in ids


@pytest.mark.asyncio
async def test_delete_stakeholder_cascades_flows(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="CascadeActor", actor_type="business_actor")
    sid = s["id"]

    r1 = await _create_flow_entry(client, h, pid, "center", sid, label="sends to")
    assert r1.status_code == 201
    r2 = await _create_flow_entry(client, h, pid, sid, "center", label="returns to")
    assert r2.status_code == 201

    # Add a second stakeholder so diagram remains accessible after delete
    await _create_stakeholder(client, h, pid, name="Keeper", actor_type="business_actor")

    r_del = await client.delete(f"{BASE}/projects/{pid}/stakeholders/{sid}", headers=h)
    assert r_del.status_code == 204

    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    remaining_flows = r_get.json()["data"]["flows"]
    sources = {f["source"] for f in remaining_flows}
    targets = {f["target"] for f in remaining_flows}
    assert sid not in sources
    assert sid not in targets


@pytest.mark.asyncio
async def test_delete_none_actor_does_not_affect_diagram(client):
    h, pid = await _setup(client)
    base = await _create_stakeholder(client, h, pid, name="Base", actor_type="business_actor")
    spectator = await _create_stakeholder(client, h, pid, name="Spectator", actor_type="none")

    r = await client.delete(f"{BASE}/projects/{pid}/stakeholders/{spectator['id']}", headers=h)
    assert r.status_code == 204

    # Diagram still intact
    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    ids = [s["id"] for s in r_get.json()["data"]["stakeholders"]]
    assert base["id"] in ids


# ── POST /flows ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_flow_201_with_generated_id(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="EndUser")

    r = await _create_flow_entry(client, h, pid, "center", s["id"], label="notifies")
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert "id" in data
    assert data["source"] == "center"
    assert data["target"] == s["id"]
    assert data["label"] == "notifies"


@pytest.mark.asyncio
async def test_create_flow_422_invalid_source(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="Ref")
    r = await _create_flow_entry(client, h, pid, str(uuid.uuid4()), s["id"], label="x")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_invalid_target(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="Ref2")
    r = await _create_flow_entry(client, h, pid, "center", str(uuid.uuid4()), label="x")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_source_equals_target(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="SelfLoop")
    r = await _create_flow_entry(client, h, pid, "center", "center", label="self")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_stakeholder_source_equals_target(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="SelfRef")
    r = await _create_flow_entry(client, h, pid, s["id"], s["id"], label="self-loop")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_422_both_endpoints_non_center(client):
    h, pid = await _setup(client)
    s1 = await _create_stakeholder(client, h, pid, name="Actor1")
    s2 = await _create_stakeholder(client, h, pid, name="Actor2")
    r = await _create_flow_entry(client, h, pid, s1["id"], s2["id"], label="direct")
    assert r.status_code == 422


# ── PATCH /flows/{id} ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_flow_label_200(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="UpdateTarget")
    r_create = await _create_flow_entry(client, h, pid, "center", s["id"], label="original")
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
    await _create_stakeholder(client, h, pid, name="GhostFlowBase")
    r = await client.patch(
        f"{BASE}/projects/{pid}/context-diagram/flows/{uuid.uuid4()}",
        json={"label": "nope"},
        headers=h,
    )
    assert r.status_code == 404


# ── DELETE /flows/{id} ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_flow_204(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="DeleteFlowTarget")
    r_create = await _create_flow_entry(client, h, pid, "center", s["id"], label="temp")
    flow_id = r_create.json()["data"]["id"]

    r = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/flows/{flow_id}", headers=h
    )
    assert r.status_code == 204

    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    flow_ids = [f["id"] for f in r_get.json()["data"]["flows"]]
    assert flow_id not in flow_ids


@pytest.mark.asyncio
async def test_delete_flow_404_not_found(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="FlowDel404")
    r = await client.delete(
        f"{BASE}/projects/{pid}/context-diagram/flows/{uuid.uuid4()}", headers=h
    )
    assert r.status_code == 404


# ── PUT /layout ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_layout_200(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="LayoutNode")

    r = await client.put(
        f"{BASE}/projects/{pid}/context-diagram/layout",
        json={
            "nodes": [
                {"id": "center", "position": {"x": 400, "y": 300}},
                {"id": s["id"], "position": {"x": 100, "y": 100}},
            ],
            "edges": [],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Layout saved."


@pytest.mark.asyncio
async def test_save_layout_persisted_in_get(client):
    h, pid = await _setup(client)
    s = await _create_stakeholder(client, h, pid, name="PersistedNode")

    await client.put(
        f"{BASE}/projects/{pid}/context-diagram/layout",
        json={
            "nodes": [
                {"id": "center", "position": {"x": 500, "y": 500}},
                {"id": s["id"], "position": {"x": 200, "y": 200}},
            ],
            "edges": [{"id": "edge-1", "waypoint": None, "source_anchor": None,
                       "target_anchor": None, "label_offset": None}],
        },
        headers=h,
    )

    r_get = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h)
    assert r_get.status_code == 200
    layout = r_get.json()["data"]["layout"]
    assert layout is not None
    center_node = next(n for n in layout["nodes"] if n["id"] == "center")
    assert center_node["position"]["x"] == 500


# ── POST /sync ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_404_if_no_diagram(client):
    h, pid = await _setup(client)
    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sync_no_op_when_no_flow_actions(client):
    h, pid = await _setup(client)
    await _create_stakeholder(client, h, pid, name="InitialNode")

    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["added_stakeholders"] == 0
    assert data["added_flows"] == 0


@pytest.mark.asyncio
async def test_sync_adds_flows_from_flow_actions(client):
    h, pid = await _setup(client)
    actor = await _create_stakeholder(client, h, pid, name="SyncActor")

    pf = await _create_project_flow(client, h, pid, code="FL-10", name="Sync Test Flow")
    r_action = await client.post(
        f"{BASE}/projects/{pid}/flows/{pf['id']}/actions",
        json=[{"description": "System sends report to user", "order": 1, "actor_id": actor["id"]}],
        headers=h,
    )
    assert r_action.status_code == 201, r_action.text

    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["added_flows"] >= 1
    actor_ids = [s["id"] for s in data["diagram"]["stakeholders"]]
    assert actor["id"] in actor_ids


@pytest.mark.asyncio
async def test_sync_idempotent_on_second_call(client):
    h, pid = await _setup(client)
    actor = await _create_stakeholder(client, h, pid, name="IdempotentActor")

    pf = await _create_project_flow(client, h, pid, code="FL-20", name="Idempotent Flow")
    await client.post(
        f"{BASE}/projects/{pid}/flows/{pf['id']}/actions",
        json=[{"description": "Actor submits form", "order": 1, "actor_id": actor["id"]}],
        headers=h,
    )

    r1 = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r1.status_code == 200

    r2 = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h)
    assert r2.status_code == 200
    d2 = r2.json()["data"]
    assert d2["added_stakeholders"] == 0
    assert d2["added_flows"] == 0


# ── Auth ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_context_diagram_401_unauthenticated(client):
    h, pid = await _setup(client)
    r = await client.get(f"{BASE}/projects/{pid}/context-diagram")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_context_diagram_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)
    r = await client.get(f"{BASE}/projects/{pid}/context-diagram", headers=h_other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_flow_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)
    s = await _create_stakeholder(client, h_owner, pid, name="FlowMember")

    r = await client.post(
        f"{BASE}/projects/{pid}/context-diagram/flows",
        json={"source": "center", "target": s["id"], "label": "x"},
        headers=h_other,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sync_403_non_member(client):
    h_owner, pid = await _setup(client)
    h_other = await make_auth_headers(client)
    r = await client.post(f"{BASE}/projects/{pid}/context-diagram/sync", headers=h_other)
    assert r.status_code == 403
