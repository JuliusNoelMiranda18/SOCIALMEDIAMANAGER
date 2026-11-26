import os
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Must run before any `app` import: point the app at a throwaway database and media dir.
_main_url = make_url(os.environ.get("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app"))
_test_url = _main_url.set(database="app_test")
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="media_test_")
os.environ["LLM_PROVIDER"] = "none"
os.environ["TOKEN_ENCRYPTION_KEY"] = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="  # test only
os.environ["FAKE_CLIENT_ID"] = "test-client"
os.environ["FAKE_CLIENT_SECRET"] = "test-secret"

_admin = create_engine(_main_url, isolation_level="AUTOCOMMIT")
with _admin.connect() as c:
    if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname='app_test'")):
        c.execute(text("CREATE DATABASE app_test"))
_admin.dispose()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

command.upgrade(Config("alembic.ini"), "head")

from app.db import engine  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    from app.db import SessionLocal

    with SessionLocal() as s:
        yield s
