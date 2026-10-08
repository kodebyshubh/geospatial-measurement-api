"""The real application wiring (settings, engine, lifespan, routers), not test overrides."""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.main import create_app
from tests.factories import closed_square, kml_document, placemark, polygon_xml


@pytest.fixture
def real_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'real.db'}")
    for cached in (get_settings, db.get_engine, db.get_session_factory):
        cached.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    db.get_engine().dispose()
    for cached in (get_settings, db.get_engine, db.get_session_factory):
        cached.cache_clear()


def test_full_stack_upload_and_read(real_client, tmp_path):
    assert real_client.get("/health").json() == {"status": "ok"}
    kml = kml_document(placemark("P", polygon_xml(closed_square(77.59, 12.97)))).encode()
    created = real_client.post("/api/files/", files={"file": ("a.kml", kml)})
    assert created.status_code == 201
    fid = created.json()["id"]
    page = real_client.get(f"/api/files/{fid}/measurements/").json()
    assert page["features"][0]["measurement"]["status"] == "MEASURED"
    assert (tmp_path / "data" / "real.db").exists()


def test_openapi_lists_the_three_endpoints(real_client):
    paths = real_client.get("/openapi.json").json()["paths"]
    assert "/api/files/" in paths and "post" in paths["/api/files/"]
    assert "get" in paths["/api/files/{file_id}/"]
    assert "get" in paths["/api/files/{file_id}/measurements/"]
    assert real_client.get("/docs").status_code == 200
