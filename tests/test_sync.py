"""Tests for sync pipeline: stage, push, label validation (LABEL_INCOMPLETE)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import BASE
from tests.helpers import (
    create_epic,
    create_org,
    create_project,
    make_auth_headers,
    setup_github_connection,
)


async def _setup(client, db_session):
    h = await make_auth_headers(client)
    org = await create_org(client, h)
    proj = await create_project(client, h, org["id"])
    pid = proj["id"]
    await setup_github_connection(db_session, pid)
    return h, pid


def _mock_gh(issue_number: int = 99):
    inst = MagicMock()
    inst.post = AsyncMock(return_value={"number": issue_number, "html_url": f"https://gh/{issue_number}"})
    gh = MagicMock(return_value=inst)
    return gh


# ── LABEL_INCOMPLETE validation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_no_labels_fails_with_label_incomplete(client, db_session):
    h, pid = await _setup(client, db_session)
    epic = await create_epic(client, h, pid, title="No Labels")

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    with patch("app.routers.sync.GithubClient", _mock_gh()):
        r = await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    assert r.status_code == 200
    report = r.json()["data"]
    assert report["pushed"] == []
    failed = report["failed"]
    assert len(failed) >= 1
    assert failed[0]["error_code"] == "LABEL_INCOMPLETE"
    assert "Missing label categories" in (failed[0]["error_message"] or "")


@pytest.mark.asyncio
async def test_push_partial_labels_fails_with_label_incomplete(client, db_session):
    h, pid = await _setup(client, db_session)
    epic = await create_epic(client, h, pid, title="Partial Labels", labels=["type:epic"])

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    with patch("app.routers.sync.GithubClient", MagicMock()):
        r = await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    assert r.status_code == 200
    fails = [f for f in r.json()["data"]["failed"] if f["error_code"] == "LABEL_INCOMPLETE"]
    assert fails


@pytest.mark.asyncio
async def test_push_all_label_prefixes_succeeds(client, db_session):
    h, pid = await _setup(client, db_session)
    epic = await create_epic(
        client, h, pid, title="Full Labels",
        labels=["type:epic", "status:open", "priority:high"],
    )

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    with patch("app.routers.sync.GithubClient", _mock_gh(1)):
        r = await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    assert r.status_code == 200
    report = r.json()["data"]
    label_fails = [f for f in report["failed"] if f["error_code"] == "LABEL_INCOMPLETE"]
    assert not label_fails
    assert len(report["pushed"]) == 1


@pytest.mark.asyncio
async def test_push_failure_appears_in_sync_logs(client, db_session):
    h, pid = await _setup(client, db_session)
    epic = await create_epic(client, h, pid, title="Log Test")

    await client.post(
        f"{BASE}/projects/{pid}/sync/stage",
        json={"items": [{"item_type": "epic", "item_id": epic["id"]}]},
        headers=h,
    )

    with patch("app.routers.sync.GithubClient", MagicMock()):
        await client.post(f"{BASE}/projects/{pid}/sync/push", headers=h)

    r = await client.get(f"{BASE}/projects/{pid}/sync/logs", headers=h)
    assert r.status_code == 200
    label_logs = [lg for lg in r.json()["data"] if lg.get("error_code") == "LABEL_INCOMPLETE"]
    assert label_logs
