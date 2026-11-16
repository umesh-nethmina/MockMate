from sqlalchemy import create_engine, inspect

from app.db import run_migrations


def test_migrations_create_all_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"sessions", "messages", "evaluations", "reports", "llm_calls"} <= tables
