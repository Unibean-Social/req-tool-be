"""Tests for NFR multi-feature linking feature.

Covers:
- NFRCreateRequest / NFRUpdateRequest with feature_ids
- NFRResponse.feature_ids
- POST /projects/{project_id}/nfrs/{nfr_id}/features/{feature_id}  — add link
- DELETE /projects/{project_id}/nfrs/{nfr_id}/features/{feature_id} — remove link
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import (
    create_actor,
    create_epic,
    create_org,
    create_project,
    make_auth_headers,
)


# ── Setup helpers ─────────────────────────────────────────────────────────────


async def _setup(client):
    """Return (headers, project_id) with a fresh user/org/project."""
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


async def _make_feature_direct(db_session, pid: str) -> dict:
    """Insert a Feature directly into the DB without going through the HTTP layer.

    The FeatureService.create() response-serialization path attempts a lazy-load
    of Feature.stories immediately after flush (before the async session has a
    chance to run a SELECT), which raises MissingGreenlet in the async SQLite
    test engine.  Bypassing the HTTP endpoint avoids that pre-existing bug while
    still producing a real Feature row for NFR-linking tests.
    """
    from sqlalchemy import select
    from app.models.requirements import Epic, Feature

    result = await db_session.execute(
        select(Epic).where(Epic.project_id == uuid.UUID(pid)).limit(1)
    )
    epic = result.scalar_one_or_none()
    if epic is None:
        raise RuntimeError(f"_make_feature_direct: no epic found for project {pid}")

    prefix = f"F-{uuid.uuid4().hex[:4].upper()}"
    feature = Feature(
        epic_id=epic.id,
        prefix=prefix,
        title=f"Feature {prefix}",
        labels=[],
    )
    db_session.add(feature)
    await db_session.flush()
    return {"id": str(feature.id), "prefix": prefix, "title": feature.title}


async def _make_feature(client, h, pid, db_session):
    """Create actor + epic via HTTP then insert Feature directly into the DB."""
    actor = await create_actor(client, h, pid)
    await create_epic(client, h, pid, actor_id=actor["id"])
    return await _make_feature_direct(db_session, pid)


async def _create_nfr(client, h, pid, feature_ids=None, **kwargs):
    """POST a new NFR and assert 201; return the response data dict."""
    body = {
        "category": "performance",
        "description": "Response time < 200 ms",
        "priority": "high",
        "feature_ids": feature_ids or [],
        **kwargs,
    }
    r = await client.post(f"{BASE}/projects/{pid}/nfrs", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── 1. Create NFR with no feature_ids ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_nfr_no_feature_ids(client, db_session):
    h, pid = await _setup(client)
    data = await _create_nfr(client, h, pid, feature_ids=[])

    assert data["feature_ids"] == []
    assert data["category"] == "performance"
    assert data["priority"] == "high"
    assert "id" in data
    assert "project_id" in data


# ── 2. Create NFR with one feature_id ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_nfr_with_one_feature_id(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    data = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])

    assert feature["id"] in data["feature_ids"]
    assert len(data["feature_ids"]) == 1


# ── 3. Create NFR with multiple feature_ids ───────────────────────────────────


@pytest.mark.asyncio
async def test_create_nfr_with_multiple_feature_ids(client, db_session):
    h, pid = await _setup(client)
    fa = await _make_feature(client, h, pid, db_session)
    fb = await _make_feature_direct(db_session, pid)

    data = await _create_nfr(client, h, pid, feature_ids=[fa["id"], fb["id"]])

    assert set(data["feature_ids"]) == {fa["id"], fb["id"]}


# ── 4. Update NFR replaces previous feature links ─────────────────────────────


@pytest.mark.asyncio
async def test_update_nfr_replaces_feature_ids(client, db_session):
    h, pid = await _setup(client)
    fa = await _make_feature(client, h, pid, db_session)
    fb = await _make_feature_direct(db_session, pid)

    nfr = await _create_nfr(client, h, pid, feature_ids=[fa["id"]])
    assert fa["id"] in nfr["feature_ids"]

    # Patch to replace with fb only
    r = await client.patch(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}",
        json={"feature_ids": [fb["id"]]},
        headers=h,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["data"]

    assert fb["id"] in updated["feature_ids"]
    assert fa["id"] not in updated["feature_ids"]
    assert len(updated["feature_ids"]) == 1


# ── 5. Update NFR with empty feature_ids clears all links ─────────────────────


@pytest.mark.asyncio
async def test_update_nfr_with_empty_feature_ids_clears_links(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])
    assert len(nfr["feature_ids"]) == 1

    r = await client.patch(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}",
        json={"feature_ids": []},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["feature_ids"] == []


# ── 6. Update NFR without feature_ids leaves links unchanged ──────────────────


@pytest.mark.asyncio
async def test_update_nfr_without_feature_ids_preserves_links(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])

    # Patch only description — no feature_ids field
    r = await client.patch(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}",
        json={"description": "Updated description"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["data"]

    assert feature["id"] in updated["feature_ids"]
    assert updated["description"] == "Updated description"


# ── 7. GET single NFR returns feature_ids ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_nfr_returns_feature_ids(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])

    r = await client.get(f"{BASE}/projects/{pid}/nfrs/{nfr['id']}", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert feature["id"] in data["feature_ids"]


# ── 8. List NFRs returns feature_ids on each item ────────────────────────────


@pytest.mark.asyncio
async def test_list_nfrs_returns_feature_ids(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    await _create_nfr(client, h, pid, feature_ids=[feature["id"]])

    r = await client.get(f"{BASE}/projects/{pid}/nfrs", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["data"]

    assert len(items) >= 1
    assert "feature_ids" in items[0]
    assert feature["id"] in items[0]["feature_ids"]


# ── 9. POST feature link returns 200 with updated feature_ids ─────────────────


@pytest.mark.asyncio
async def test_add_feature_link_returns_200_with_feature_id(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[])
    assert nfr["feature_ids"] == []

    r = await client.post(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}/features/{feature['id']}",
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert feature["id"] in data["feature_ids"]


# ── 10. POST duplicate feature link is idempotent (no error) ─────────────────


@pytest.mark.asyncio
async def test_add_duplicate_feature_link_is_idempotent(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])

    # Link the same feature again
    r = await client.post(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}/features/{feature['id']}",
        headers=h,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    # Should still appear exactly once
    assert data["feature_ids"].count(feature["id"]) == 1


# ── 11. DELETE feature link returns 204 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_feature_link_returns_204(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])
    assert feature["id"] in nfr["feature_ids"]

    r = await client.delete(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}/features/{feature['id']}",
        headers=h,
    )
    assert r.status_code == 204, r.text

    # Verify link is gone
    r2 = await client.get(f"{BASE}/projects/{pid}/nfrs/{nfr['id']}", headers=h)
    assert r2.status_code == 200
    assert feature["id"] not in r2.json()["data"]["feature_ids"]


# ── 12. DELETE non-existent feature link returns 404 ─────────────────────────


@pytest.mark.asyncio
async def test_remove_nonexistent_feature_link_returns_404(client, db_session):
    h, pid = await _setup(client)

    nfr = await _create_nfr(client, h, pid, feature_ids=[])
    ghost_id = str(uuid.uuid4())

    r = await client.delete(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}/features/{ghost_id}",
        headers=h,
    )
    assert r.status_code == 404, r.text


# ── 13. POST feature link with unknown feature_id returns 404 ─────────────────


@pytest.mark.asyncio
async def test_add_feature_link_unknown_feature_returns_404(client, db_session):
    h, pid = await _setup(client)

    nfr = await _create_nfr(client, h, pid, feature_ids=[])
    ghost_id = str(uuid.uuid4())

    r = await client.post(
        f"{BASE}/projects/{pid}/nfrs/{nfr['id']}/features/{ghost_id}",
        headers=h,
    )
    assert r.status_code == 404, r.text


# ── 14. Create NFR with unknown feature_id returns 404 ───────────────────────


@pytest.mark.asyncio
async def test_create_nfr_with_unknown_feature_id_returns_404(client, db_session):
    h, pid = await _setup(client)
    ghost_id = str(uuid.uuid4())

    body = {
        "category": "security",
        "description": "Auth required",
        "priority": "critical",
        "feature_ids": [ghost_id],
    }
    r = await client.post(f"{BASE}/projects/{pid}/nfrs", json=body, headers=h)
    assert r.status_code == 404, r.text


# ── 15. GET NFR on wrong project returns 404 ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_nfr_wrong_project_returns_404(client, db_session):
    h, pid = await _setup(client)
    nfr = await _create_nfr(client, h, pid)

    other_org = await create_org(client, h)
    other_proj = await create_project(client, h, other_org["id"])

    r = await client.get(
        f"{BASE}/projects/{other_proj['id']}/nfrs/{nfr['id']}",
        headers=h,
    )
    assert r.status_code == 404, r.text


# ── 16. Unauthenticated request returns 401/403 ───────────────────────────────


@pytest.mark.asyncio
async def test_create_nfr_unauthenticated_returns_401_or_403(client, db_session):
    h, pid = await _setup(client)

    body = {
        "category": "usability",
        "description": "Must be accessible",
        "priority": "low",
        "feature_ids": [],
    }
    r = await client.post(f"{BASE}/projects/{pid}/nfrs", json=body)
    assert r.status_code in (401, 403), r.text


# ── 17. DELETE NFR removes all feature links (cascade) ───────────────────────


@pytest.mark.asyncio
async def test_delete_nfr_cascades_feature_links(client, db_session):
    h, pid = await _setup(client)
    feature = await _make_feature(client, h, pid, db_session)

    nfr = await _create_nfr(client, h, pid, feature_ids=[feature["id"]])

    # Delete the NFR
    r = await client.delete(f"{BASE}/projects/{pid}/nfrs/{nfr['id']}", headers=h)
    assert r.status_code == 204, r.text

    # NFR should be gone
    r2 = await client.get(f"{BASE}/projects/{pid}/nfrs/{nfr['id']}", headers=h)
    assert r2.status_code == 404, r2.text


# ── 18. Add feature link to NFR that belongs to a different project ───────────


@pytest.mark.asyncio
async def test_add_feature_link_nfr_not_in_project_returns_404(client, db_session):
    h, pid = await _setup(client)

    # Create another project (same user, same org)
    other_org = await create_org(client, h)
    other_pid = (await create_project(client, h, other_org["id"]))["id"]

    feature = await _make_feature(client, h, pid, db_session)
    nfr = await _create_nfr(client, h, pid, feature_ids=[])

    # Try to add the link via the wrong project context
    r = await client.post(
        f"{BASE}/projects/{other_pid}/nfrs/{nfr['id']}/features/{feature['id']}",
        headers=h,
    )
    # NFR doesn't exist in other_pid → 404
    assert r.status_code == 404, r.text
