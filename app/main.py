import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pythonjsonlogger import jsonlogger

from app.config import settings
from app.database import engine
from app.core.errors import http_exception_handler, validation_exception_handler, unhandled_exception_handler
from app.routers import auth, github_auth, users, organizations, projects, actors


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG if settings.app_debug else logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    yield
    await engine.dispose()


app = FastAPI(
    title="ReqFlow API",
    version="1.0.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth.router)
app.include_router(github_auth.router)
app.include_router(users.router)
app.include_router(organizations.router)
app.include_router(projects.router)
app.include_router(actors.router)


@app.get("/", tags=["health"], include_in_schema=False)
async def root():
    return {"name": "ReqFlow API", "version": "1.0.0", "docs": "/docs"}


@app.get("/health", tags=["health"])
async def health():
    from sqlalchemy import text
    from app.database import async_session_factory
    async with async_session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}
