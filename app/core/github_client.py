import httpx
from fastapi import HTTPException, status

_BASE = "https://api.github.com"
_GRAPHQL_URL = "https://api.github.com/graphql"

REQFLOW_LABELS = [
    # type
    {"name": "type:epic",          "color": "0052cc", "description": "Top-level capability"},
    {"name": "type:feature",       "color": "5319e7", "description": "Feature within an epic"},
    {"name": "type:story",         "color": "0075ca", "description": "User story"},
    {"name": "type:task",          "color": "e4e669", "description": "Implementation task"},
    {"name": "type:bug",           "color": "d73a4a", "description": "Bug report"},
    # status
    {"name": "status:draft",       "color": "ededed", "description": "Draft"},
    {"name": "status:in-progress", "color": "fbca04", "description": "In progress"},
    {"name": "status:done",        "color": "0e8a16", "description": "Done"},
    {"name": "status:rejected",    "color": "ee0701", "description": "Rejected"},
    {"name": "status:duplicate",   "color": "cfd3d7", "description": "Duplicate"},
    {"name": "status:deferred",    "color": "b60205", "description": "Deferred"},
    # priority
    {"name": "priority:low",       "color": "c5def5", "description": "Low priority"},
    {"name": "priority:medium",    "color": "0075ca", "description": "Medium priority"},
    {"name": "priority:high",      "color": "e99695", "description": "High priority"},
    {"name": "priority:critical",  "color": "b60205", "description": "Critical priority"},
    # level
    {"name": "level:1-epic",       "color": "bfd4f2", "description": "Hierarchy level: Epic"},
    {"name": "level:2-feature",    "color": "d4c5f9", "description": "Hierarchy level: Feature"},
    {"name": "level:3-story",      "color": "c2e0c6", "description": "Hierarchy level: Story"},
    {"name": "level:4-task",       "color": "fef2c0", "description": "Hierarchy level: Task"},
    # actor
    {"name": "actor",              "color": "f9d0c4", "description": "Actor (append name after colon)"},
    # misc
    {"name": "misc:blocked",       "color": "e11d48", "description": "Blocked by dependency"},
    {"name": "misc:needs-triage",  "color": "e4e669", "description": "Needs triage"},
]

SPRINT_MILESTONE_TITLE = "Sprint 1"
BOARD_TITLE = "ReqFlow Sprint Board"
BOARD_COLUMNS = ["Backlog", "Todo", "In Progress", "In Review", "Done"]


class GithubClient:
    def __init__(self, token: str):
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get(self, path: str, params: dict | None = None) -> dict | list:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{_BASE}{path}", headers=self._headers, params=params, timeout=15)
            _raise_for_status(resp)
            return resp.json()

    async def post(self, path: str, json: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{_BASE}{path}", headers=self._headers, json=json, timeout=15)
            _raise_for_status(resp)
            return resp.json()

    async def patch(self, path: str, json: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(f"{_BASE}{path}", headers=self._headers, json=json, timeout=15)
            _raise_for_status(resp)
            return resp.json()

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _GRAPHQL_URL,
                headers={**self._headers, "Accept": "application/json"},
                json=payload,
                timeout=15,
            )
            _raise_for_status(resp)
            data = resp.json()
            if errors := data.get("errors"):
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    detail=f"GitHub GraphQL error: {errors[0]['message']}",
                )
            return data["data"]


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 401:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="GitHub token invalid or expired")
    if resp.status_code == 403:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="GitHub token lacks required permissions")
    if resp.status_code == 404:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="GitHub resource not found — check repo owner/name")
    if not resp.is_success:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error {resp.status_code}: {resp.text[:200]}",
        )
