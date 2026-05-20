"""Tests for requirement CRUD, auto-references, and NFR advisory."""
import uuid

import pytest

from tests.helpers import (
    create_epic,
    create_feature,
    create_story,
    create_task,
    create_org,
    create_project,
    epic_references,
    feature_references,
    make_auth_headers,
    story_references,
)
from tests.conftest import BASE

# ── Fixtures ──────────────────────────────────────────────────────────────────


async def _setup(client):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    return h, proj["id"]


# ── Auto-references ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feature_create_adds_to_epic_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    refs = await epic_references(db_session, epic["id"])
    assert feature["prefix"] in refs


@pytest.mark.asyncio
async def test_story_create_adds_to_feature_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])
    refs = await feature_references(db_session, feature["id"])
    assert story["prefix"] in refs


@pytest.mark.asyncio
async def test_task_create_adds_to_story_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])
    task = await create_task(client, h, pid, story["id"])
    refs = await story_references(db_session, story["id"])
    assert task["prefix"] in refs


@pytest.mark.asyncio
async def test_feature_delete_removes_from_epic_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])

    refs_before = await epic_references(db_session, epic["id"])
    assert feature["prefix"] in refs_before

    r = await client.delete(f"{BASE}/projects/{pid}/features/{feature['id']}", headers=h)
    assert r.status_code == 204

    refs_after = await epic_references(db_session, epic["id"])
    assert feature["prefix"] not in refs_after


@pytest.mark.asyncio
async def test_story_delete_removes_from_feature_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])

    refs_before = await feature_references(db_session, feature["id"])
    assert story["prefix"] in refs_before

    r = await client.delete(f"{BASE}/projects/{pid}/stories/{story['id']}", headers=h)
    assert r.status_code == 204

    refs_after = await feature_references(db_session, feature["id"])
    assert story["prefix"] not in refs_after


@pytest.mark.asyncio
async def test_task_delete_removes_from_story_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    story = await create_story(client, h, pid, feature["id"])
    task = await create_task(client, h, pid, story["id"])

    refs_before = await story_references(db_session, story["id"])
    assert task["prefix"] in refs_before

    r = await client.delete(f"{BASE}/projects/{pid}/tasks/{task['id']}", headers=h)
    assert r.status_code == 204

    refs_after = await story_references(db_session, story["id"])
    assert task["prefix"] not in refs_after


@pytest.mark.asyncio
async def test_multiple_features_accumulate_in_epic_references(client, db_session):
    h, pid = await _setup(client)
    epic = await create_epic(client, h, pid)
    f1 = await create_feature(client, h, pid, epic["id"], title="F1")
    f2 = await create_feature(client, h, pid, epic["id"], title="F2")
    refs = await epic_references(db_session, epic["id"])
    assert f1["prefix"] in refs
    assert f2["prefix"] in refs


