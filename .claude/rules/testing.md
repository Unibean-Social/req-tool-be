---
paths:
  - "tests/**/*.py"
---

# Testing Rules

- `BASE = "/api/v1"` from `conftest.py` — must prefix every test URL.
- Default item status is `"draft"`, not `"open"`.
- Terminal statuses (`done`, `rejected`, `duplicate`, `wont_fix`) require `PATCH /{resource}/{id}/close` — direct PATCH to set status returns 422.
- `CloseRequest` body: `{"reason": "done|rejected|duplicate|wont_fix", "comment": "<non-empty>"}`.
- Use `make_auth_headers(client)` from `tests/helpers.py` — never call the login endpoint directly in tests.
- 4 tests are permanently skipped — JSONB array operators not supported on SQLite.
