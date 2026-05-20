"""
Task endpoints: CRUD, close.

Covers:
- POST /projects/{project_id}/tasks
- GET  /projects/{project_id}/tasks  (story_id filter)
- GET  /projects/{project_id}/tasks/{task_id}
- PATCH /projects/{project_id}/tasks/{task_id}
- DELETE /projects/{project_id}/tasks/{task_id}
- PATCH /projects/{project_id}/tasks/{task_id}/close
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
    epic = await create_epic(client, h, proj["id"])
    feature = await create_feature(client, h, proj["id"], epic["id"])
    story = await create_story(client, h, proj["id"], feature["id"])
    return h, proj["id"], story["id"]


# ── CRUD ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_task_success(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id, title="Write unit tests")

    assert task["title"] == "Write unit tests"
    assert task["story_id"] == story_id
    assert task["status"] == "draft"
    assert "id" in task


@pytest.mark.asyncio
async def test_list_tasks_returns_created_task(client):
    h, pid, story_id = await _setup(client)
    await create_task(client, h, pid, story_id, title="Task A")

    r = await client.get(f"{BASE}/projects/{pid}/tasks", headers=h)
    assert r.status_code == 200
    assert any(t["title"] == "Task A" for t in r.json()["data"])


@pytest.mark.asyncio
async def test_list_tasks_filter_by_story_id(client):
    h, pid, story_id = await _setup(client)
    # Create a second story to test isolation
    epic = await create_epic(client, h, pid)
    feature = await create_feature(client, h, pid, epic["id"])
    other_story = await create_story(client, h, pid, feature["id"])

    await create_task(client, h, pid, story_id, title="In Story A")
    await create_task(client, h, pid, other_story["id"], title="In Other Story")

    r = await client.get(
        f"{BASE}/projects/{pid}/tasks",
        params={"story_id": story_id},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert all(t["story_id"] == story_id for t in data)
    assert len(data) == 1
    assert data[0]["title"] == "In Story A"


@pytest.mark.asyncio
async def test_get_task_by_id(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id, title="Specific Task")

    r = await client.get(f"{BASE}/projects/{pid}/tasks/{task['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Specific Task"


@pytest.mark.asyncio
async def test_get_task_not_found(client):
    h, pid, _ = await _setup(client)

    r = await client.get(f"{BASE}/projects/{pid}/tasks/{uuid.uuid4()}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_task_title(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id, title="Old Task Title")

    r = await client.patch(
        f"{BASE}/projects/{pid}/tasks/{task['id']}",
        json={"title": "Updated Task Title"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Updated Task Title"


@pytest.mark.asyncio
async def test_update_task_terminal_status_via_patch_returns_422(client):
    """Terminal status must go through /close — PATCH with done must fail."""
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id)

    r = await client.patch(
        f"{BASE}/projects/{pid}/tasks/{task['id']}",
        json={"status": "done"},
        headers=h,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_task_success(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id)

    r = await client.delete(f"{BASE}/projects/{pid}/tasks/{task['id']}", headers=h)
    assert r.status_code == 204

    r2 = await client.get(f"{BASE}/projects/{pid}/tasks/{task['id']}", headers=h)
    assert r2.status_code == 404


# ── Close transition ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_task_success(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id)

    r = await client.patch(
        f"{BASE}/projects/{pid}/tasks/{task['id']}/close",
        json={"reason": "done", "comment": "Task completed"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "done"


@pytest.mark.asyncio
async def test_close_task_duplicate_reason(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id)

    r = await client.patch(
        f"{BASE}/projects/{pid}/tasks/{task['id']}/close",
        json={"reason": "duplicate", "comment": "Same as task #5"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "duplicate"


@pytest.mark.asyncio
async def test_close_task_empty_comment_returns_422(client):
    h, pid, story_id = await _setup(client)
    task = await create_task(client, h, pid, story_id)

    r = await client.patch(
        f"{BASE}/projects/{pid}/tasks/{task['id']}/close",
        json={"reason": "done", "comment": ""},
        headers=h,
    )
    assert r.status_code == 422


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tasks_non_member_returns_403(client):
    h_owner = await make_auth_headers(client)
    h_other = await make_auth_headers(client)
    org = await create_org(client, h_owner)
    proj = await create_project(client, h_owner, org["id"])

    r = await client.get(f"{BASE}/projects/{proj['id']}/tasks", headers=h_other)
    assert r.status_code == 403
