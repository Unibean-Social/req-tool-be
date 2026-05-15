# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# First-time setup
task setup              # create .venv + install deps

# Infrastructure (Docker required)
task infra:up           # start PostgreSQL (5432) + pgAdmin (5050)
task infra:down

# Run
task dev                # migrate → uvicorn with --reload at 127.0.0.1:8000
task up                 # infra:up + dev in one command

# Database
task db:upgrade         # alembic upgrade head
task db:revision -- 'describe change'   # autogenerate migration
task db:downgrade

# Tests
pytest                              # full suite
pytest tests/path/test_file.py      # single file
pytest -k "test_name"               # single test by name
pytest -x                           # stop on first failure
```

`.env` must exist before running (copy `.env.example`). Activate `.venv` before running any commands directly.

## Architecture

### Stack
FastAPI + SQLAlchemy 2.0 async + asyncpg + PostgreSQL. Alembic for migrations. Pydantic v2 / pydantic-settings for config and schemas. JWT (python-jose HS256) + bcrypt for auth. Fernet (cryptography) for token-at-rest encryption.

### Request/Response Contract

Every non-204 endpoint returns `ApiResponse[T]` (`app/schemas/response.py`):
```json
{"success": true, "data": {...}, "message": "..."}
```
Use `ok(data, message)` or `created(data, message)` from `app/core/responses.py` as the return value — FastAPI serializes through the `response_model`.

Errors use RFC 7807 Problem Detail (`app/core/errors.py`) with added `request_id` and `errors[]` fields. Three registered handlers: `HTTPException`, `RequestValidationError`, unhandled `Exception`.

### Auth

**JWT**: Two-token system — access (30 min) + refresh (7 days). Token payload: `{sub: user_id, exp, type: "access"|"refresh"}`. `decode_token()` returns `{}` on failure; callers check truthiness.

**`current_user` dep** (`app/deps.py`): composes HTTPBearer → decode → DB lookup. Inject via `Depends(current_user)`.

**Password hashing**: HMAC-SHA256 with pepper (defaults to `jwt_secret_key` in dev, independent `PASSWORD_PEPPER` in prod) → base64 → bcrypt. Never pass raw password to bcrypt.

**GitHub OAuth**: Stateless CSRF via HMAC-signed state + httpOnly cookie nonce. Cookie deleted after use. Tokens encrypted with Fernet before DB storage (`encrypt_token` / `decrypt_token` in `app/core/crypto.py`).

### Database Session

`get_db()` in `app/database.py` — yields `AsyncSession`, commits on success, rolls back on exception. Add entities with `db.add(obj)` then `db.flush()` (not `commit`) to get the generated ID while still inside the request transaction.

```python
db.add(entity)
await db.flush()          # get entity.id, stay in transaction
return created(entity)    # dependency commits on response
```

### Model Hierarchy

```
User → OrgMember → Organization → Project → Actor
                                           → GithubConnection (1:1)
```

All models inherit `AuditMixin` (`app/models/base.py`): UUID PK, `created_at`, `updated_at` (server-side UTC). `OrgMember` has `UniqueConstraint(org_id, user_id)`.

### Authorization Guards

Consolidated authorization checks in `app/core/guards.py`:
```python
require_org_member(org_id, user, db) -> OrgMember
require_org_owner(org_id, user, db) -> OrgMember
require_project_access(project_id, user, db) -> Project
require_sprint(sprint_id, project_id, db) -> Sprint
```
Call these at the top of each router handler to verify access before delegating to a service.

### Service Layer

Business logic lives in `app/services/` organized by domain:
- `OrgService`, `ProjectService`, `SprintService`, `ActorService` — core domain services
- `AuthService`, `GithubService`, `SyncService` — external integration and auth
- `EpicService`, `FeatureService`, `StoryService`, `TaskService` — requirement-specific services under `app/services/requirements/`

Each service is instantiated via a factory function in `app/deps.py` and injected into routers:
```python
def get_org_service(db: AsyncSession = Depends(get_db)) -> OrgService:
    return OrgService(db)
```

Routers remain thin HTTP adapters: they validate input, call guards for authorization, invoke service methods, and return responses via `ok()` or `created()`.

### Config & Secrets

`app/config.py` — `Settings` (pydantic-settings). Loaded from `.env`. Production enforces: `JWT_SECRET_KEY` ≥ 32 chars, `ENCRYPTION_KEY`, `PASSWORD_PEPPER`, `GITHUB_CLIENT_ID/SECRET` must be set. Fails at startup if violated.

`AUTO_MIGRATE=false` is set by Taskfile `dev`/`start` tasks because they run `alembic upgrade head` explicitly — prevents the lifespan hook from running a second migration.

### Adding a New Resource

1. **Model**: Create in `app/models/` inheriting `AuditMixin` + `Base`; import in `app/models/__init__.py` (required for Alembic)
2. **Migration**: `task db:revision -- 'add <resource> table'`
3. **Schemas**: Create in `app/schemas/` — `CreateRequest`, `UpdateRequest`, `Response` (with `from_attributes=True`)
4. **Service**: Create a service class in `app/services/` (or `app/services/requirements/` for requirement types) with methods for create, read, update, delete operations
5. **Service Factory**: Add a factory function in `app/deps.py` (e.g., `def get_foo_service(db) -> FooService`)
6. **Router**: Create thin HTTP adapter in `app/routers/` with `APIRouter(prefix=..., tags=[...])`; inject service via `Depends(get_foo_service)` and call service methods
7. **Registration**: Register router in `app/main.py` under `api_v1`

### Testing

Tests use SQLite in-memory via `aiosqlite`. `conftest.py` patches `app.database.engine` and the session factory before any test runs. The `BASE = "/api/v1"` constant in `conftest.py` must prefix all test paths. Login responses are wrapped: `resp.json()["data"]["access_token"]`.

`db_session` fixture overrides `get_db` per-test; each test auto-commits then rolls back at teardown.
