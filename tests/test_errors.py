from fastapi import APIRouter, Query

from app import errors
from app.api import health
from app.schemas import ErrorResponse, FeatureOut, FileInfo, MeasurementsPage

router = APIRouter()


@router.get("/raise/{kind}")
def raise_it(kind: str):
    mapping = {
        "invalid": errors.InvalidRequest("bad"),
        "notfound": errors.FileNotFound("nope"),
        "notcompleted": errors.FileNotCompleted("wait"),
        "toolarge": errors.FileTooLarge("big"),
        "unsupported": errors.UnsupportedFileType("type"),
        "unprocessable": errors.UnprocessableFile("broken", file_id="abc"),
    }
    if kind == "boom":
        raise RuntimeError("secret /server/path detail")
    raise mapping[kind]


@router.get("/q")
def q(limit: int = Query(10, ge=1, le=1000)):
    return {"limit": limit}


def test_each_error_has_documented_status_and_code(make_client):
    client = make_client(router)
    expected = {
        "invalid": (400, "INVALID_REQUEST"),
        "notfound": (404, "FILE_NOT_FOUND"),
        "notcompleted": (409, "FILE_NOT_COMPLETED"),
        "toolarge": (413, "FILE_TOO_LARGE"),
        "unsupported": (415, "UNSUPPORTED_FILE_TYPE"),
        "unprocessable": (422, "UNPROCESSABLE_FILE"),
    }
    for kind, (status, code) in expected.items():
        r = client.get(f"/raise/{kind}")
        assert r.status_code == status
        assert r.json()["error"]["code"] == code
        ErrorResponse.model_validate(r.json())


def test_file_id_only_present_when_set(make_client):
    client = make_client(router)
    assert client.get("/raise/unprocessable").json()["error"]["file_id"] == "abc"
    assert "file_id" not in client.get("/raise/invalid").json()["error"]


def test_unexpected_error_is_generic(make_client):
    r = make_client(router).get("/raise/boom")
    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}
    }
    assert "secret" not in r.text


def test_validation_error_becomes_400_envelope(make_client):
    r = make_client(router).get("/q?limit=0")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
    assert "limit" in r.json()["error"]["message"]


def test_health(make_client):
    r = make_client(health.router).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_schemas_match_api_examples():
    info = {
        "id": "3f2b8c1e9a7d4c5e8b6a1d2c3e4f5a6b",
        "filename": "survey.kml",
        "file_type": "KML",
        "status": "COMPLETED",
        "crs": "EPSG:4326",
        "feature_count": 120,
        "error_message": None,
        "created_at": "2026-10-07T14:30:00Z",
    }
    assert FileInfo.model_validate(info).model_dump(mode="json") == info

    page = {
        "file_id": "x",
        "total": 1,
        "limit": 100,
        "offset": 0,
        "features": [
            {
                "index": 0,
                "geometry_type": "Polygon",
                "crs": "EPSG:4326",
                "properties": {"name": "Plot A"},
                "measurement": {
                    "status": "MEASURED",
                    "area_m2": 10432.77,
                    "length_m": None,
                    "measurement_crs": "EPSG:32643",
                    "message": None,
                },
            }
        ],
    }
    parsed = MeasurementsPage.model_validate(page)
    assert parsed.model_dump(mode="json", exclude_unset=True) == page
    assert FeatureOut.model_fields["geometry"].default is None
