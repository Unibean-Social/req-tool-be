---
paths:
  - "app/**/*.py"
---

# Endpoint Rules

- Routers are thin adapters only: call guard → call service → return response. No business logic in routers.
- Always call a guard from `app/core/guards.py` before any service call: `require_project_access`, `require_org_member`, `require_org_owner`, `require_sprint`.
- Inject auth via `Depends(current_user)` — never re-implement token extraction in routers.
- Never pass raw passwords to bcrypt — pepper+hash first via `app/core/auth.py`.
- GitHub tokens must be encrypted with Fernet before DB storage — use `encrypt_token` / `decrypt_token` from `app/core/crypto.py`.
