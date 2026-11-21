"""Tests that touch the API need Postgres (docker compose up -d). A throwaway
database is created per session from DATABASE_URL (default: compose credentials),
migrated with alembic, and dropped afterwards."""

import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from alembic import command
from api.db import database_url

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def _db_url():
    base = make_url(database_url())
    name = f"test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT",
                          connect_args={"connect_timeout": 5})
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as e:
        pytest.fail(
            f"Postgres unreachable at {base.render_as_string(hide_password=True)}: run "
            f"`docker compose up -d` at the repo root or set DATABASE_URL. ({e.orig})",
            pytrace=False,
        )
    url = base.set(database=name).render_as_string(hide_password=False)
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    yield url
    from api.db import _engine

    _engine.cache_clear()  # dispose handled by GC; drop needs no open connections
    if old is None:
        del os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = old
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.fixture(autouse=True)
def _need_db(request):
    # engine-only tests run without Postgres; modules that import TestClient need it
    if "db" in request.fixturenames or hasattr(request.module, "TestClient"):
        request.getfixturevalue("_db_url")
