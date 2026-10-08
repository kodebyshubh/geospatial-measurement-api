import json

import pytest
from shapely.geometry import Polygon

from app.api import files
from app.errors import FileNotFound
from app.schemas import ErrorResponse, FileInfo, MeasurementsPage
from tests.factories import (
    closed_square,
    folder,
    kml_document,
    linestring_xml,
    make_gdf,
    make_zip,
    placemark,
    point_xml,
    polygon_xml,
    square,
    write_shapefile_zip,
)

MB = 1024 * 1024


@pytest.fixture
def client(make_client):
    return make_client(files.router)


def kml_bytes():
    return kml_document(
        placemark("Plot A", polygon_xml(closed_square(77.59, 12.97, 0.01))),
        placemark("Road 1", linestring_xml([(77.59, 12.97), (77.60, 12.98)])),
        placemark("Gate", point_xml((77.595, 12.975))),
    ).encode()


def post(client, data: bytes, filename: str):
    return client.post("/api/files/", files={"file": (filename, data)})


def error_of(response) -> dict:
    ErrorResponse.model_validate(response.json())
    return response.json()["error"]


# --- upload (US1, US2) --------------------------------------------------------------


def test_upload_kml_returns_201_and_file_info(client):
    r = post(client, kml_bytes(), "survey.kml")
    assert r.status_code == 201
    body = r.json()
    FileInfo.model_validate(body)
    assert set(body) == {
        "id", "filename", "file_type", "status", "crs",
        "feature_count", "error_message", "created_at",
    }  # fmt: skip
    assert len(body["id"]) == 32
    assert body["filename"] == "survey.kml" and body["file_type"] == "KML"
    assert body["status"] == "COMPLETED" and body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 3 and body["error_message"] is None
    assert body["created_at"].endswith("Z")


def test_upload_zipped_shapefile(client, tmp_path):
    gdf = make_gdf([square(77.59, 12.97)], name=["a"]).to_crs(32643)
    z = write_shapefile_zip(gdf, tmp_path / "p.zip")
    r = post(client, z.read_bytes(), "parcels.zip")
    assert r.status_code == 201
    assert r.json()["file_type"] == "SHAPEFILE" and r.json()["crs"] == "EPSG:32643"


def test_client_filename_path_is_not_stored(client):
    r = post(client, kml_bytes(), "../../secret/evil.kml")
    assert r.status_code == 201 and r.json()["filename"] == "evil.kml"


def test_two_uploads_are_independent(client):
    a = post(client, kml_bytes(), "a.kml").json()
    b = post(client, kml_bytes(), "b.kml").json()
    assert a["id"] != b["id"]
    for item in (a, b):
        assert client.get(f"/api/files/{item['id']}/measurements/").json()["total"] == 3


# --- file info (US3) ----------------------------------------------------------------


def test_get_file_info_matches_upload_response(client):
    created = post(client, kml_bytes(), "survey.kml").json()
    r = client.get(f"/api/files/{created['id']}/")
    assert r.status_code == 200 and r.json() == created


def test_get_unknown_file_404(client):
    r = client.get("/api/files/does-not-exist/")
    assert r.status_code == 404 and error_of(r)["code"] == FileNotFound.code


# --- measurements (US4, US5) --------------------------------------------------------


def test_measurements_exact_shape(client):
    fid = post(client, kml_bytes(), "survey.kml").json()["id"]
    r = client.get(f"/api/files/{fid}/measurements/")
    assert r.status_code == 200
    body = r.json()
    MeasurementsPage.model_validate(body)
    assert (body["file_id"], body["total"], body["limit"], body["offset"]) == (fid, 3, 100, 0)
    assert [f["index"] for f in body["features"]] == [0, 1, 2]

    polygon, line, point = body["features"]
    assert set(polygon) == {"index", "geometry_type", "crs", "properties", "measurement"}
    assert polygon["geometry_type"] == "Polygon" and polygon["crs"] == "EPSG:4326"
    assert polygon["properties"]["Name"] == "Plot A"
    assert polygon["measurement"]["status"] == "MEASURED"
    assert 1_000_000 < polygon["measurement"]["area_m2"] < 1_500_000
    assert polygon["measurement"]["length_m"] is None
    assert polygon["measurement"]["measurement_crs"] == "EPSG:32643"
    assert polygon["measurement"]["message"] is None

    assert line["geometry_type"] == "LineString"
    assert line["measurement"]["length_m"] > 0 and line["measurement"]["area_m2"] is None

    assert point["measurement"] == {
        "status": "NOT_APPLICABLE",
        "area_m2": None,
        "length_m": None,
        "measurement_crs": None,
        "message": "Points have no measurement.",
    }


def test_measurements_pagination(client):
    fid = post(client, kml_bytes(), "survey.kml").json()["id"]
    r = client.get(f"/api/files/{fid}/measurements/?limit=2&offset=1").json()
    assert (r["total"], r["limit"], r["offset"]) == (3, 2, 1)
    assert [f["index"] for f in r["features"]] == [1, 2]
    assert client.get(f"/api/files/{fid}/measurements/?offset=10").json()["features"] == []


def test_include_geometry_flag(client):
    fid = post(client, kml_bytes(), "survey.kml").json()["id"]
    plain = client.get(f"/api/files/{fid}/measurements/").json()["features"][0]
    with_geom = client.get(f"/api/files/{fid}/measurements/?include_geometry=true").json()
    assert "geometry" not in plain
    geom = with_geom["features"][0]["geometry"]
    assert geom["type"] == "Polygon" and len(geom["coordinates"][0]) == 5


def test_mixed_statuses_reported_not_fatal(client, tmp_path):
    bow = Polygon([(77.5, 12.9), (77.51, 12.91), (77.51, 12.9), (77.5, 12.91)])
    gdf = make_gdf([square(77.59, 12.97), bow, None, square(77.7, 12.97)])
    z = write_shapefile_zip(gdf, tmp_path / "p.zip")
    fid = post(client, z.read_bytes(), "p.zip").json()["id"]
    statuses = [
        f["measurement"]["status"]
        for f in client.get(f"/api/files/{fid}/measurements/").json()["features"]
    ]
    assert statuses == ["MEASURED", "INVALID", "INVALID", "MEASURED"]


@pytest.mark.parametrize("query", ["limit=0", "limit=1001", "offset=-1", "limit=abc"])
def test_bad_query_parameters_400(client, query):
    fid = post(client, kml_bytes(), "survey.kml").json()["id"]
    r = client.get(f"/api/files/{fid}/measurements/?{query}")
    assert r.status_code == 400 and error_of(r)["code"] == "INVALID_REQUEST"


def test_measurements_unknown_id_404(client):
    assert client.get("/api/files/nope/measurements/").status_code == 404


# --- error paths (US7) --------------------------------------------------------------


@pytest.mark.parametrize("name", ["a.geojson", "a.kmz", "a.shp", "noext"])
def test_unsupported_extension_415(client, name):
    r = post(client, b"<kml/>", name)
    assert r.status_code == 415 and error_of(r)["code"] == "UNSUPPORTED_FILE_TYPE"


def test_content_mismatch_415(client):
    assert post(client, b"not a zip at all", "a.zip").status_code == 415
    assert post(client, b"PK\x03\x04", "a.kml").status_code == 415


def test_empty_file_400(client):
    r = post(client, b"", "a.kml")
    assert r.status_code == 400 and error_of(r)["code"] == "INVALID_REQUEST"


def test_missing_file_part_400(client):
    r = client.post("/api/files/", data={"x": "y"})
    assert r.status_code == 400 and error_of(r)["code"] == "INVALID_REQUEST"


def test_oversize_413(client, settings):
    settings.max_upload_mb = 1
    r = post(client, b"<" + b"x" * (2 * MB), "big.kml")
    assert r.status_code == 413 and error_of(r)["code"] == "FILE_TOO_LARGE"


def test_failed_file_flow_missing_prj(client, tmp_path):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "p.zip", include_prj=False)
    r = post(client, z.read_bytes(), "p.zip")
    assert r.status_code == 422
    err = error_of(r)
    assert err["code"] == "UNPROCESSABLE_FILE" and "no .prj" in err["message"]

    info = client.get(f"/api/files/{err['file_id']}/")
    assert info.status_code == 200
    assert info.json()["status"] == "FAILED" and "no .prj" in info.json()["error_message"]
    assert info.json()["feature_count"] == 0

    m = client.get(f"/api/files/{err['file_id']}/measurements/")
    assert m.status_code == 409 and error_of(m)["code"] == "FILE_NOT_COMPLETED"


def test_zip_slip_422(client, tmp_path):
    z = make_zip(tmp_path / "z.zip", {"../evil.txt": b"x", "data.shp": b"x"})
    r = post(client, z.read_bytes(), "z.zip")
    assert r.status_code == 422 and "unsafe" in error_of(r)["message"]
    assert not (tmp_path.parent / "evil.txt").exists()


def test_corrupt_kml_422(client):
    r = post(client, b"<kml><Document><Placemark>", "bad.kml")
    assert r.status_code == 422 and error_of(r)["code"] == "UNPROCESSABLE_FILE"
    assert error_of(r)["file_id"]


def test_empty_kml_422(client):
    r = post(client, kml_document(folder("Empty")).encode(), "empty.kml")
    assert r.status_code == 422 and "no features" in error_of(r)["message"]


def test_error_messages_never_leak_paths_or_tracebacks(client):
    r = post(client, b"<kml><Document><Placemark>", "bad.kml")
    text = json.dumps(r.json())
    assert "/tmp" not in text and "Traceback" not in text and "upload.kml" not in text


# Edge case matrix: test that covers each case
# EC-1 test_unsupported_extension_415          EC-2 test_content_mismatch_415
# EC-3 test_empty_file_400                     EC-4 test_oversize_413
# EC-5/6/7/8/9/10 test_upload_service.py       EC-11 test_corrupt_kml_422
# EC-12 test_empty_kml_422                     EC-13/14/15/16/17 test_measure.py
# EC-18/19/20/21/22/23 test_measure.py         EC-24 documented limitation (README)
# EC-25 test_measure.py (feet CRS)             EC-26 test_pipeline.py (JSON safe attributes)
# EC-27 test_get_unknown_file_404              EC-28 test_failed_file_flow_missing_prj
# EC-29 test_bad_query_parameters_400          EC-30 test_client_filename_path_is_not_stored
# EC-31 test_two_uploads_are_independent
