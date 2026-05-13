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

### Authorization Pattern

Routers define private `_require_*` async helpers that raise `HTTPException(403/404)`:
```python
async def _require_member(org_id, user, db) -> Organization: ...
async def _require_owner(org_id, user, db) -> Organization: ...
```
Call these at the top of each handler instead of repeating the same query+check logic.

### Config & Secrets

`app/config.py` — `Settings` (pydantic-settings). Loaded from `.env`. Production enforces: `JWT_SECRET_KEY` ≥ 32 chars, `ENCRYPTION_KEY`, `PASSWORD_PEPPER`, `GITHUB_CLIENT_ID/SECRET` must be set. Fails at startup if violated.

`AUTO_MIGRATE=false` is set by Taskfile `dev`/`start` tasks because they run `alembic upgrade head` explicitly — prevents the lifespan hook from running a second migration.

### Adding a New Resource

1. Model in `app/models/` inheriting `AuditMixin` + `Base`
2. Import in `app/models/__init__.py` (required for Alembic autogenerate)
3. Schemas in `app/schemas/` — `CreateRequest`, `UpdateRequest`, `Response` (with `from_attributes=True`)
4. Router in `app/routers/` with `APIRouter(prefix=..., tags=[...])`
5. Register in `app/main.py` under `api_v1`
6. `task db:revision -- 'add <resource> table'`

### Testing

Tests use SQLite in-memory via `aiosqlite`. `conftest.py` patches `app.database.engine` and the session factory before any test runs. The `BASE = "/api/v1"` constant in `conftest.py` must prefix all test paths. Login responses are wrapped: `resp.json()["data"]["access_token"]`.

`db_session` fixture overrides `get_db` per-test; each test auto-commits then rolls back at teardown.
