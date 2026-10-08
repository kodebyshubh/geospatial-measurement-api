import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import Settings, get_settings
from app.db import create_db_engine
from app.models import Feature, File, FileStatus, FileType, MeasurementStatus


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.max_upload_mb == 25
    assert s.max_upload_bytes == 25 * 1024 * 1024
    assert s.max_zip_entries == 50
    assert s.database_url.startswith("sqlite")


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    try:
        assert get_settings().max_upload_mb == 1
        assert get_settings().max_upload_bytes == 1024 * 1024
    finally:
        get_settings.cache_clear()


def test_engine_creates_parent_dir_and_enables_foreign_keys(tmp_path):
    path = tmp_path / "nested" / "dir" / "x.db"
    engine = create_db_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert path.parent.exists()
    engine.dispose()


def _file_with_features(db, n=3):
    f = File(filename="a.kml", file_type=FileType.KML, status=FileStatus.COMPLETED)
    db.add(f)
    db.flush()
    for i in reversed(range(n)):  # insert out of order on purpose
        db.add(
            Feature(
                file_id=f.id,
                feature_index=i,
                geometry_type="Point",
                geometry={"type": "Point", "coordinates": [1, 2]},
                properties={"name": f"p{i}", "nested": {"a": [1, 2]}},
                measurement_status=MeasurementStatus.NOT_APPLICABLE,
            )
        )
    db.commit()
    return f


def test_file_and_features_round_trip_in_order(db_session):
    f = _file_with_features(db_session)
    assert len(f.id) == 32
    db_session.expire_all()
    loaded = db_session.get(File, f.id)
    assert [x.feature_index for x in loaded.features] == [0, 1, 2]
    assert loaded.features[0].properties["nested"] == {"a": [1, 2]}
    assert loaded.created_at is not None


def test_null_geometry_is_stored_as_sql_null(db_session):
    f = File(filename="a.kml", file_type=FileType.KML)
    db_session.add(f)
    db_session.flush()
    db_session.add(
        Feature(
            file_id=f.id,
            feature_index=0,
            geometry=None,
            properties={},
            measurement_status=MeasurementStatus.INVALID,
        )
    )
    db_session.commit()
    value = db_session.execute(text("SELECT geometry FROM features")).scalar()
    assert value is None


def test_delete_file_cascades_to_features(db_session):
    f = _file_with_features(db_session)
    db_session.delete(f)
    db_session.commit()
    assert db_session.query(Feature).count() == 0


def test_duplicate_feature_index_rejected(db_session):
    f = _file_with_features(db_session, n=1)
    db_session.add(
        Feature(file_id=f.id, feature_index=0, properties={}, measurement_status="INVALID")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
