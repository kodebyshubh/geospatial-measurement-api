import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import create_db_engine, get_db, init_db, make_session_factory
from app.errors import register_exception_handlers


@pytest.fixture
def engine(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine):
    session = make_session_factory(engine)()
    yield session
    session.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        max_upload_mb=5,
        max_uncompressed_mb=20,
        max_zip_entries=20,
        max_features=1000,
    )


@pytest.fixture
def make_client(engine, settings):
    """Build a TestClient for an app with the given routers, wired to the temp database."""

    def _make(*routers) -> TestClient:
        app = FastAPI()
        register_exception_handlers(app)
        for router in routers:
            app.include_router(router)
        factory = make_session_factory(engine)

        def _get_db():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_settings] = lambda: settings
        return TestClient(app, raise_server_exceptions=False)

    return _make
