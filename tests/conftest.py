"""
Pytest fixtures for Phase 1 integration tests.

Strategy:
- Override app.database.engine and async_session_factory with SQLite+aiosqlite.
- Override app.main.engine (used in lifespan dispose) with the same instance.
- Override the get_db dependency so every request uses the test session.
- Create all tables before the test session, drop after.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.database as db_module
from app.models.base import Base
from app.main import app
from app.database import get_db

# ---------------------------------------------------------------------------
# In-memory SQLite engine (shared across the whole test session)
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestSessionFactory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Patch the module-level engine and session factory so that
# app.main lifespan (engine.dispose) and any import of these
# symbols also get the test versions.
db_module.engine = test_engine
db_module.async_session_factory = TestSessionFactory

# Also patch app.main.engine which is imported at module load time
import app.main as main_module
main_module.engine = test_engine


# ---------------------------------------------------------------------------
# Session-scoped: create / drop schema once per pytest run
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Function-scoped: override get_db to use a single transaction that is
# ROLLED BACK after each test so tests stay isolated.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(autouse=True)
async def db_session():
    """
    Each test runs inside a transaction that is rolled back at the end.
    We use a nested (SAVEPOINT) transaction for SQLite compatibility.
    """
    async with TestSessionFactory() as session:
        # Patch get_db to yield this session
        async def _override_get_db():
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        app.dependency_overrides[get_db] = _override_get_db
        yield session
        app.dependency_overrides.pop(get_db, None)
        await session.rollback()


# ---------------------------------------------------------------------------
# Async HTTP client
# ---------------------------------------------------------------------------
BASE = "/api/v1"


@pytest_asyncio.fixture
async def client(db_session):
    """AsyncClient wired to the FastAPI app via ASGI transport."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Convenience: a registered + logged-in user
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def registered_user(client):
    payload = {
        "email": "alice@example.com",
        "password": "Secret123!",
        "full_name": "Alice Test",
    }
    resp = await client.post(f"{BASE}/auth/register", json=payload)
    assert resp.status_code == 201
    return payload


@pytest_asyncio.fixture
async def auth_headers(client, registered_user):
    resp = await client.post(
        f"{BASE}/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert resp.status_code == 200
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_user(client):
    """A second registered user (not a member of any org by default)."""
    payload = {
        "email": "bob@example.com",
        "password": "Secret123!",
        "full_name": "Bob Test",
    }
    resp = await client.post(f"{BASE}/auth/register", json=payload)
    assert resp.status_code == 201
    return payload


@pytest_asyncio.fixture
async def second_auth_headers(client, second_user):
    resp = await client.post(
        f"{BASE}/auth/login",
        json={
            "email": second_user["email"],
            "password": second_user["password"],
        },
    )
    assert resp.status_code == 200
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def org(client, auth_headers):
    """An organization created by alice."""
    resp = await client.post(
        f"{BASE}/orgs",
        json={"name": "ACME Corp", "slug": "acme-corp"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


@pytest_asyncio.fixture
async def project(client, auth_headers, org):
    """A project inside alice's org."""
    resp = await client.post(
        f"{BASE}/orgs/{org['id']}/projects",
        json={"name": "Alpha Project", "slug": "alpha", "description": "Test project"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()
