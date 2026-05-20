---
paths:
  - "app/**/*.py"
  - "alembic/**/*.py"
---

# Code Structure Rules

- New resource chain: model → migration → schemas → service → factory in `deps.py` → router → register in `main.py`.
- Requirement services go in `app/services/requirements/`, not the root services folder.
- All models inherit `AuditMixin` (UUID PK, `created_at`, `updated_at` server-side UTC); import in `app/models/__init__.py` for Alembic.
- Use `db.flush()` inside transactions, never `db.commit()` — `get_db()` handles commit/rollback.
- Always call `await db.refresh(entity)` after `flush()` when the response includes server-side columns. Missing this causes `MissingGreenlet`.
- Response schemas must set `model_config = ConfigDict(from_attributes=True)`.
