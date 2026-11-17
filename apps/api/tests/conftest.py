"""Test setup: fixed secrets and a separate test database, migrated from scratch each session."""
import base64
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL",
                             "postgresql+psycopg://foxhood:foxhood@localhost:5432/foxhood_test")

# Set before the app is imported; the real .env never overrides these (load_dotenv doesn't override).
os.environ["API_JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["FOXHOOD_DATA_KEYS"] = "v1:" + base64.b64encode(b"\x07" * 32).decode()
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["DB_NULLPOOL"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"   # tests never send traces to LangSmith

API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def test_database():
    url = make_url(TEST_DB_URL)
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)).fetchone():
            conn.execute(f'CREATE DATABASE "{url.database}"')
    cfg = Config(str(API_ROOT / "alembic.ini"))
    command.downgrade(cfg, "base")  # every session starts empty, and downgrade gets exercised too
    command.upgrade(cfg, "head")
    yield
    
@pytest.fixture
async def session():
    from db.session import SessionLocal
    async with SessionLocal() as s:
        yield s


@pytest.fixture
def make_user(session):
    """Creates a fresh user (unique email) and returns a UserRepo bound to them."""
    from db.repo import AdminRepo, UserRepo

    async def _make():
        user = await AdminRepo(session).get_or_create_user(f"{uuid.uuid4().hex[:10]}@example.com")
        return UserRepo(session, user.id)

    return _make

@pytest.fixture
async def client():
    import httpx

    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def invited_user(session):
    """Invites a fresh email and returns (auth headers, email, google_sub) for that user."""
    from db.repo import AdminRepo
    from tests.helpers import bearer, make_token

    async def _make(name: str = "Test User"):
        email, sub = f"{uuid.uuid4().hex[:10]}@example.com", f"g-{uuid.uuid4().hex[:12]}"
        await AdminRepo(session).invite(email, invited_by="test")
        return bearer(make_token(email, sub, name=name)), email, sub

    return _make



@pytest.fixture(autouse=True)
def fake_market(monkeypatch, test_database):
    """Every test gets the fake market-data providers (tests/fakes.py): no network, no API keys."""
    from tests.fakes import install
    return install(monkeypatch)


@pytest.fixture
def signed_in(client, invited_user, session):
    """Invites + signs in a fresh user through the API; returns (auth headers, UserRepo for them)."""
    from db.repo import AdminRepo, UserRepo

    async def _make():
        headers, email, _ = await invited_user()
        assert (await client.get("/me", headers=headers)).status_code == 200
        user = await AdminRepo(session).find_user(email)
        return headers, UserRepo(session, user.id)
    return _make