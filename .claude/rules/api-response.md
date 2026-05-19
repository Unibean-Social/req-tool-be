---
paths:
  - "app/**/*.py"
---

# API Response Rules

- Every non-204 response must use `ok(data, msg)` or `created(data, msg)` from `app/core/responses.py` — never return raw dicts.
- Response shape: `{"success": true, "data": {...}, "message": "..."}` wrapped in `ApiResponse[T]`.
- Errors use RFC 7807 Problem Detail via handlers in `app/core/errors.py` — never raise plain `Exception` in routers.
- 204 responses return no body; use `status_code=204` and `response_model=None`.
