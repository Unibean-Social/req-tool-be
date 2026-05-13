import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _problem(status_code: int, title: str, detail: str, instance: str = None) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if instance:
        body["instance"] = instance
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    titles = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        422: "Unprocessable Entity",
        500: "Internal Server Error",
    }
    title = titles.get(exc.status_code, "Error")
    return _problem(exc.status_code, title, str(exc.detail), str(request.url))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    detail = "; ".join(
        f"{' -> '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in errors
    )
    return _problem(status.HTTP_422_UNPROCESSABLE_ENTITY, "Validation Error", detail, str(request.url))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url, exc_info=exc)
    return _problem(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Internal Server Error",
        "An unexpected error occurred.",
        str(request.url),
    )
