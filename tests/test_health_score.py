"""
Project health score endpoint: GET /projects/{project_id}/health
"""
import uuid

import pytest

from tests.conftest import BASE
from tests.helpers import (
    create_epic,
    create_feature,
    create_org,
    create_project,
    create_story,
    create_task,
    make_auth_headers,
)


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


def _skip_if_jsonb_unavailable(resp, exc):
    if exc is not None:
        msg = str(exc).lower()
        if any(kw in msg for kw in ("jsonb", "unsupportedcompilationerror", "visit_jsonb")):
            pytest.skip("JSONB not available on SQLite")
        raise exc
    if resp.status_code == 500:
        body = resp.text.lower()
        if any(kw in body for kw in ("jsonpath", "jsonb", "@?", "operator", "visit_jsonb")):
            pytest.skip("JSONB not available on SQLite")
        pytest.fail(f"Unexpected 500: {resp.text}")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _get_health(client, pid, h):
    try:
        r = await client.get(f"{BASE}/projects/{pid}/health", headers=h)
        return r, None
    except Exception as exc:
        return None, exc


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_returns_required_keys(client):
    h, pid = await _setup(client)
    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert {"ac_coverage", "label_completeness", "close_hygiene", "overall", "item_counts"}.issubset(data)
    for k in ("epics", "features", "stories", "tasks"):
        assert k in data["item_counts"]


@pytest.mark.asyncio
async def test_health_empty_project_defaults_to_100(client):
    h, pid = await _setup(client)
    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert data["item_counts"] == {"epics": 0, "features": 0, "stories": 0, "tasks": 0}
    assert data["ac_coverage"] == 100
    assert data["close_hygiene"] == 100


@pytest.mark.asyncio
async def test_health_item_counts_reflect_created_items(client):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])
    await create_task(client, h, pid, story["id"])

    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert data["item_counts"] == {"epics": 1, "features": 1, "stories": 1, "tasks": 1}


@pytest.mark.asyncio
async def test_health_overall_is_int_in_range(client):
    h, pid = await _setup(client)
    r, exc = await _get_health(client, pid, h)
    data = _skip_if_jsonb_unavailable(r, exc)

    assert isinstance(data["overall"], int)
    assert 0 <= data["overall"] <= 100


@pytest.mark.asyncio
async def test_health_403_for_non_member(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/health", headers=h_other)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_health_404_unknown_project(client):
    h = await make_auth_headers(client)
    r = await client.get(f"{BASE}/projects/{uuid.uuid4()}/health", headers=h)
    assert r.status_code == 404
