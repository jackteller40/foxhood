"""Test setup: fixed secrets and a separate test database, migrated from scratch each session."""
import base64
import os
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
os.environ["ALLOWED_EMAILS"] = "test@example.com"
os.environ["FOXHOOD_DATA_KEYS"] = "v1:" + base64.b64encode(b"\x07" * 32).decode()
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["DB_NULLPOOL"] = "1"

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