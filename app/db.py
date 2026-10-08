"""Database engine, session factory and the FastAPI session dependency."""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def create_db_engine(url: str) -> Engine:
    """Create an engine. SQLite gets thread-safe settings and foreign keys switched on."""
    kwargs: dict = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        database = make_url(url).database
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@lru_cache
def get_engine() -> Engine:
    return create_db_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


def init_db(engine: Engine) -> None:
    """Create all tables (no migrations in the MVP)."""
    from app import models  # noqa: F401  (registers the tables on Base.metadata)

    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()
