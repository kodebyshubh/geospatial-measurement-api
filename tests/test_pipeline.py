import datetime as dt
import json
import tempfile

import pytest
from shapely.geometry import LineString, Polygon
from sqlalchemy import select

from app.errors import UnprocessableFile, UnsupportedFileType
from app.models import Feature, File, FileStatus, FileType, MeasurementStatus
from app.services import pipeline
from app.services.pipeline import process_upload
from tests.factories import (
    closed_square,
    folder,
    kml_document,
    linestring_xml,
    make_gdf,
    placemark,
    point_xml,
    polygon_xml,
    square,
    upload_file,
    write_shapefile_zip,
)


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    """Send temp directories to a known place so tests can prove they are cleaned up."""
    root = tmp_path / "tmproot"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def kml_bytes():
    return kml_document(
        placemark("Plot", polygon_xml(closed_square(77.59, 12.97, 0.01)), data={"owner": "Ravi"}),
        folder(
            "Lines",
            placemark("Road", linestring_xml([(77.59, 12.97), (77.60, 12.98)])),
            placemark("Gate", point_xml((77.595, 12.975))),
        ),
    ).encode()


def features_of(db, file_id):
    return list(
        db.scalars(
            select(Feature).where(Feature.file_id == file_id).order_by(Feature.feature_index)
        )
    )


def test_kml_success(db_session, settings, temp_root):
    file = process_upload(db_session, upload_file(kml_bytes(), "survey.kml"), settings)

    assert file.status == FileStatus.COMPLETED
    assert file.file_type == FileType.KML
    assert file.crs == "EPSG:4326"
    assert file.feature_count == 3
    assert file.size_bytes == len(kml_bytes())
    assert file.error_message is None

    rows = features_of(db_session, file.id)
    by_name = {r.properties["Name"]: r for r in rows}
    assert [r.feature_index for r in rows] == [0, 1, 2]
    plot, road, gate = by_name["Plot"], by_name["Road"], by_name["Gate"]
    assert plot.geometry_type == "Polygon" and plot.measurement_status == "MEASURED"
    assert 1_000_000 < plot.area_m2 < 1_500_000 and plot.length_m is None
    assert plot.measurement_crs == "EPSG:32643"
    assert plot.properties["owner"] == "Ravi"
    assert plot.geometry["type"] == "Polygon"
    assert road.length_m == pytest.approx(1500, rel=0.1) and road.area_m2 is None
    assert gate.measurement_status == MeasurementStatus.NOT_APPLICABLE
    assert list(temp_root.iterdir()) == []


def test_shapefile_success_with_properties_and_order(db_session, settings, tmp_path, temp_root):
    gdf = make_gdf(
        [square(77.59, 12.97), square(77.7, 12.97), square(77.8, 12.97)],
        name=["a", "b", "c"],
        count=[1, 2, 3],
    )
    z = write_shapefile_zip(gdf, tmp_path / "p.zip", nested_folder=True)
    file = process_upload(db_session, upload_file(z.read_bytes(), "parcels.zip"), settings)

    assert file.status == FileStatus.COMPLETED and file.file_type == FileType.SHAPEFILE
    assert file.crs == "EPSG:4326" and file.feature_count == 3
    rows = features_of(db_session, file.id)
    assert [r.properties["name"] for r in rows] == ["a", "b", "c"]
    assert [r.properties["count"] for r in rows] == [1, 2, 3]
    assert [r.geometry_type for r in rows] == ["Polygon"] * 3
    assert all(r.measurement_status == "MEASURED" and r.area_m2 > 0 for r in rows)
    assert list(temp_root.iterdir()) == []


def test_line_shapefile_gets_lengths(db_session, settings, tmp_path):
    lines = [LineString([(77.59, 12.97), (77.6, 12.97)]), LineString([(77.7, 12.9), (77.7, 12.91)])]
    z = write_shapefile_zip(make_gdf(lines), tmp_path / "l.zip")
    file = process_upload(db_session, upload_file(z.read_bytes(), "l.zip"), settings)
    first, second = features_of(db_session, file.id)
    assert first.length_m == pytest.approx(1085, rel=0.01)
    assert second.length_m == pytest.approx(1105, rel=0.01)
    assert first.area_m2 is None


def test_projected_shapefile_reports_native_crs_and_meters(db_session, settings, tmp_path):
    gdf = make_gdf([square(77.5, 12.9, 0.001)], name=["a"]).to_crs(32643)
    z = write_shapefile_zip(gdf, tmp_path / "p.zip")
    file = process_upload(db_session, upload_file(z.read_bytes(), "p.zip"), settings)
    assert file.crs == "EPSG:32643"
    [row] = features_of(db_session, file.id)
    assert row.geometry["coordinates"][0][0][0] > 100_000  # native (projected) coordinates kept
    assert 10_000 < row.area_m2 < 15_000


def test_invalid_feature_does_not_stop_others(db_session, settings, tmp_path):
    bow = Polygon([(77.5, 12.9), (77.51, 12.91), (77.51, 12.9), (77.5, 12.91)])
    gdf = make_gdf([square(77.59, 12.97), bow, None, square(77.7, 12.97)], name=list("abcd"))
    z = write_shapefile_zip(gdf, tmp_path / "p.zip")
    file = process_upload(db_session, upload_file(z.read_bytes(), "p.zip"), settings)

    assert file.status == FileStatus.COMPLETED and file.feature_count == 4
    rows = features_of(db_session, file.id)
    assert [r.measurement_status for r in rows] == ["MEASURED", "INVALID", "INVALID", "MEASURED"]
    assert "Self-intersection" in rows[1].measurement_message
    assert rows[2].geometry is None and rows[2].geometry_type is None


def test_attributes_with_nan_dates_and_unicode_are_stored_json_safe(db_session, settings, tmp_path):
    gdf = make_gdf(
        [square(77.59, 12.97), square(77.7, 12.97)],
        value=[1.5, float("nan")],
        when=[dt.date(2020, 1, 2), dt.date(2021, 3, 4)],
        label=["é 名前", None],
    )
    z = write_shapefile_zip(gdf, tmp_path / "p.zip")
    file = process_upload(db_session, upload_file(z.read_bytes(), "p.zip"), settings)
    for row in features_of(db_session, file.id):
        json.dumps(row.properties, allow_nan=False)
    first, second = features_of(db_session, file.id)
    assert first.properties["value"] == 1.5 and second.properties["value"] is None
    assert first.properties["when"].startswith("2020-01-02")
    assert first.properties["label"] == "é 名前"


def test_missing_prj_creates_failed_record_and_raises_with_id(
    db_session, settings, tmp_path, temp_root
):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "p.zip", include_prj=False)
    with pytest.raises(UnprocessableFile, match=r"no \.prj") as info:
        process_upload(db_session, upload_file(z.read_bytes(), "p.zip"), settings)

    file = db_session.get(File, info.value.file_id)
    assert file.status == FileStatus.FAILED
    assert "no .prj" in file.error_message
    assert file.feature_count == 0 and file.crs is None
    assert features_of(db_session, file.id) == []
    assert list(temp_root.iterdir()) == []


def test_kml_without_features_fails(db_session, settings):
    with pytest.raises(UnprocessableFile, match="no features") as info:
        process_upload(
            db_session, upload_file(kml_document(folder("E")).encode(), "e.kml"), settings
        )
    assert db_session.get(File, info.value.file_id).status == FileStatus.FAILED


def test_upload_level_errors_create_no_record(db_session, settings):
    with pytest.raises(UnsupportedFileType):
        process_upload(db_session, upload_file(b"{}", "a.geojson"), settings)
    assert db_session.scalars(select(File)).all() == []


def test_unexpected_error_marks_failed_with_generic_message(db_session, settings, monkeypatch):
    def boom(_gdf):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(pipeline, "measure_features", boom)
    with pytest.raises(RuntimeError):
        process_upload(db_session, upload_file(kml_bytes(), "a.kml"), settings)
    [file] = db_session.scalars(select(File)).all()
    assert file.status == FileStatus.FAILED
    assert file.error_message == pipeline.GENERIC_FAILURE
    assert "secret" not in file.error_message
    assert features_of(db_session, file.id) == []


def test_database_failure_while_storing_rolls_back_features(db_session, settings, monkeypatch):
    original = pipeline._build_feature_rows

    def duplicate_index(file_id, parsed, measurements):
        rows = original(file_id, parsed, measurements)
        rows[1]["feature_index"] = 0  # violates the unique constraint on insert
        return rows

    monkeypatch.setattr(pipeline, "_build_feature_rows", duplicate_index)
    with pytest.raises(Exception, match="UNIQUE|constraint"):
        process_upload(db_session, upload_file(kml_bytes(), "a.kml"), settings)
    [file] = db_session.scalars(select(File)).all()
    assert file.status == FileStatus.FAILED
    assert features_of(db_session, file.id) == []


def test_repository_helpers(db_session, settings):
    from app.errors import FileNotFound
    from app.services import repository

    file = process_upload(db_session, upload_file(kml_bytes(), "a.kml"), settings)
    assert repository.get_file(db_session, file.id).id == file.id
    assert repository.count_features(db_session, file.id) == 3
    page = repository.list_features(db_session, file.id, limit=2, offset=1)
    assert [f.feature_index for f in page] == [1, 2]
    with pytest.raises(FileNotFound):
        repository.get_file(db_session, "missing")
