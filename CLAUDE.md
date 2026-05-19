# CLAUDE.md

## Commands

```bash
task setup              # create .venv + install deps
task infra:up           # start PostgreSQL (5432) + pgAdmin (5050)
task infra:down
task dev                # migrate → uvicorn --reload at 127.0.0.1:8000
task up                 # infra:up + dev in one step
task db:upgrade         # alembic upgrade head
task db:revision -- 'describe change'
pytest                  # full suite
pytest tests/test_file.py -k "test_name" -x
```

`.env` must exist (copy `.env.example`). Activate `.venv` before running commands directly.

---

## Stack

FastAPI + SQLAlchemy 2.0 async + asyncpg + PostgreSQL. Alembic for migrations. Pydantic v2 for schemas. JWT HS256 + bcrypt for auth. Fernet for token-at-rest encryption.

---

## 1. Think Before Coding

### Example: Adding a new endpoint

**Request:** "Add an endpoint to list epics for a project"

**❌ What LLMs Do**

```python
@router.get("/projects/{project_id}/epics")
async def list_epics(project_id: UUID, service: EpicService = Depends(get_epic_service)):
    return ok(await service.list(project_id))
```

**Problems:**

- No auth check — any request, authenticated or not, can read any project's epics
- `current_user` not injected — no way to know who is calling
- No membership guard — org members from other projects get full access

**✅ What Should Happen**

Before writing, identify: Is this project-scoped? → yes → needs `require_project_access`. Is it owner-only? → no → member access is enough.

```python
@router.get("/projects/{project_id}/epics", response_model=ApiResponse[list[EpicResponse]])
async def list_epics(
    project_id: UUID,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    await require_project_access(project_id, user, service.db)
    return ok(await service.list(project_id))
```

---

## 2. Simplicity First

### Example: Implementing a service update method

**Request:** "Update an epic's title and description"

**❌ What LLMs Do**

```python
async def update(self, epic_id: UUID, body: EpicUpdate) -> Epic:
    epic = await self._get_or_404(epic_id)
    if body.title is not None:
        await self._validate_title_uniqueness(body.title, epic.project_id)
        await self._emit_change_event("title", epic.title, body.title)
    if body.description is not None:
        await self._archive_previous_description(epic)
    self._apply_patch(epic, body)
    await self.db.flush()
    await self._notify_watchers(epic)
    return epic
```

**Problems:**

- Uniqueness check, event emit, archive, notify — none were asked for
- Each added method needs its own tests and failure paths
- When requirements change, every speculative feature becomes debt

**✅ What Should Happen**

```python
async def update(self, epic: Epic, body: EpicUpdate) -> Epic:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(epic, field, value)
    await self.db.flush()
    await self.db.refresh(epic)
    return epic
```

Add uniqueness checks, events, or notifications only when they are explicitly required.

---

## 3. Surgical Changes

### Example: Fixing a bug in the close endpoint

**Request:** "Fix the 500 error when closing an epic with an empty comment"

**❌ What LLMs Do**

```python
# "Improved" the whole handler while fixing the bug
@router.patch("/epics/{epic_id}/close", response_model=ApiResponse[EpicResponse])
async def close_epic(
    epic_id: UUID,
    project_id: UUID,                          # added type hint
    body: CloseRequest,
    user: User = Depends(current_user),
    service: EpicService = Depends(get_epic_service),
):
    """Close an epic with a reason."""         # added docstring
    project = await require_project_access(project_id, user, service.db)
    if not body.comment or not body.comment.strip():   # the actual fix
        raise HTTPException(422, "Comment required")
    epic = await service.close(epic_id, body)
    logger.info(f"Epic {epic_id} closed")     # added logging nobody asked for
    return ok(epic)
```

**Problems:**

- Added docstring, logger, and parameter annotations beyond the fix
- Changed the existing style of the file
- The actual bug fix is one line; everything else is noise

**✅ What Should Happen**

Only touch `CloseRequest` schema — the validation belongs there, not in the router:

```python
class CloseRequest(BaseModel):
    reason: CloseReason
    comment: str

    @field_validator("comment")
    @classmethod
    def comment_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("comment must not be empty")
        return v
```

One validator, zero changes to the router.

---

## 4. Goal-Driven Execution

### Example: A test fails after updating a service

**Request:** "test_update_task_title is failing with MissingGreenlet"

**❌ What LLMs Do**

```python
# Just changes the test to avoid the error
async def test_update_task_title(client):
    ...
    r = await client.patch(f"{BASE}/tasks/{task['id']}", json={"title": "New"})
    assert r.status_code == 200
    # removed: assert r.json()["data"]["updated_at"] is not None  ← deleted the assertion
```

**Problems:**

- Hides the bug instead of fixing it
- `updated_at` is still stale on every real update — clients will cache wrong timestamps
- The next developer will hit the same bug in production

**✅ What Should Happen**

Define the goal first: _the response must contain a fresh `updated_at` after update._

1. Confirm the failure reproduces: run `pytest -k test_update_task_title -s`, read the traceback
2. Trace root cause: `MissingGreenlet` on `updated_at` → `onupdate=func.now()` is server-side → expired after `flush()` → fix is `await db.refresh(task)`
3. Fix the service, keep the assertion:

```python
async def update(self, task: Task, body: TaskUpdate) -> Task:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await self.db.flush()
    await self.db.refresh(task)   # reload server-side updated_at
    return task
```

4. Verify: test passes, no other tests regress.

---

## Rules

Detailed rules auto-injected from `.claude/rules/` by file glob:
`api-response.md` · `code-struct.md` · `endpoints.md` · `testing.md` · `code-clean.md`
