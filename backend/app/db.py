from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)
engine: Engine | None = None


def configure_database(url: str) -> Engine:
    """(Re)bind the session factory to a database URL. Tests call this with 'sqlite://'."""
    global engine
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_conn, _record):  # pragma: no cover - driver hook
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SessionLocal.configure(bind=engine)
    return engine


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(url: str | None = None) -> None:
    """Apply Alembic migrations up to head (called on app start-up)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url or get_settings().database_url
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


configure_database(get_settings().database_url)
