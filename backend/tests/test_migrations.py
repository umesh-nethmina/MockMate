import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.config import normalise_database_url
from app.db import BACKEND_DIR, run_migrations

TABLES = {"users", "cvs", "sessions", "messages", "evaluations", "reports", "llm_calls", "coding_problems", "code_runs"}


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    return cfg


def test_migrations_create_all_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    assert TABLES <= set(inspect(create_engine(url)).get_table_names())


def test_migrations_downgrade_and_upgrade_again(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    command.downgrade(_config(url), "base")
    assert not TABLES & set(inspect(create_engine(url)).get_table_names())
    run_migrations(url)
    assert TABLES <= set(inspect(create_engine(url)).get_table_names())


@pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="needs TEST_DATABASE_URL (Postgres)")
def test_migrations_on_postgres(engine):
    """The production database: full chain up, down and up again, leaving the schema empty for other tests."""
    engine.dispose()
    url = normalise_database_url(os.environ["TEST_DATABASE_URL"])
    from app.db import Base

    Base.metadata.drop_all(create_engine(url))
    try:
        run_migrations(url)
        assert TABLES <= set(inspect(create_engine(url)).get_table_names())
        command.downgrade(_config(url), "base")
        run_migrations(url)
        assert TABLES <= set(inspect(create_engine(url)).get_table_names())
    finally:
        command.downgrade(_config(url), "base")
