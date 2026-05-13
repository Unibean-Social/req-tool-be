from typing import Any


def ok(data: Any = None, message: str | None = None) -> dict:
    return {"success": True, "data": data, "message": message}


def created(data: Any = None, message: str | None = None) -> dict:
    return {"success": True, "data": data, "message": message}
