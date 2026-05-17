"""Shared helpers for API tests — auth, entity creation, DB inspection."""
import uuid as uuid_mod

import pytest
from sqlalchemy import select

from tests.conftest import BASE


async def make_auth_headers(client) -> dict:
    uid = uuid_mod.uuid4().hex[:8]
    email = f"user-{uid}@example.com"
    await client.post(
        f"{BASE}/auth/register",
        json={"email": email, "password": "Secret123!", "full_name": f"User {uid}"},
    )
    resp = await client.post(f"{BASE}/auth/login", json={"email": email, "password": "Secret123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def create_org(client, h: dict) -> dict:
    slug = f"org-{uuid_mod.uuid4().hex[:8]}"
    r = await client.post(f"{BASE}/orgs", json={"name": slug, "slug": slug}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_project(client, h: dict, org_id: str) -> dict:
    slug = f"proj-{uuid_mod.uuid4().hex[:8]}"
    r = await client.post(
        f"{BASE}/orgs/{org_id}/projects",
        json={"name": slug, "slug": slug, "description": "test"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_epic(
    client, h: dict, pid: str, actor_id: str, title: str = "Epic", labels: list | None = None
) -> dict:
    r = await client.post(
        f"{BASE}/projects/{pid}/actors/{actor_id}/epics",
        json={"title": title, "labels": labels or []},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_feature(
    client, h: dict, pid: str, epic_id: str,
    title: str = "Feature", nfr_note: str | None = None, labels: list | None = None,
) -> dict:
    body: dict = {"title": title, "labels": labels or []}
    if nfr_note is not None:
        body["nfr_note"] = nfr_note
    r = await client.post(f"{BASE}/projects/{pid}/epics/{epic_id}/features", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_story(client, h: dict, pid: str, feature_id: str, suffix: str = "") -> dict:
    """Creates a story via story-builder (requires ≥1 AC, eager-loads AC relationship)."""
    r = await client.post(
        f"{BASE}/projects/{pid}/story-builder",
        json={
            "feature_id": feature_id,
            "actor_ref": "user",
            "action_text": f"do something{suffix}",
            "goal_text": "achieve goal",
            "priority": "medium",
            "labels": [],
            "acceptance_criteria": [{"description": "AC1", "order": 0}],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def create_task(client, h: dict, pid: str, story_id: str, title: str = "Task") -> dict:
    r = await client.post(
        f"{BASE}/projects/{pid}/stories/{story_id}/tasks",
        json={"title": title, "labels": []},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def setup_github_connection(db_session, pid: str) -> None:
    from app.core.crypto import encrypt_token
    from app.models.github_connection import GithubConnection

    conn = GithubConnection(
        project_id=uuid_mod.UUID(pid),
        repo_owner="test-owner",
        repo_name="test-repo",
        access_token=encrypt_token("fake-token"),
    )
    db_session.add(conn)
    await db_session.flush()


# ── DB reference inspection (references field not exposed in API responses) ────


async def _load_references(db_session, model, pk: str) -> list:
    db_session.expire_all()
    r = await db_session.execute(select(model).where(model.id == uuid_mod.UUID(pk)))
    obj = r.scalar_one_or_none()
    return list(obj.references or []) if obj else []


async def epic_references(db_session, epic_id: str) -> list:
    from app.models.requirements import Epic
    return await _load_references(db_session, Epic, epic_id)


async def feature_references(db_session, feature_id: str) -> list:
    from app.models.requirements import Feature
    return await _load_references(db_session, Feature, feature_id)


async def story_references(db_session, story_id: str) -> list:
    from app.models.requirements import Story
    return await _load_references(db_session, Story, story_id)


def find_rule(checks: list[dict], rule: str) -> dict | None:
    return next((c for c in checks if c["rule"] == rule), None)
