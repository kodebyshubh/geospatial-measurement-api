"""Hostile input must be rejected or handled quickly, never crash the server."""

import time

import pytest

from app.api import files
from tests.factories import make_gdf, make_zip, square, write_shapefile_zip

BILLION_LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
 <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
 <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
 <!ENTITY lol6 "&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;&lol5;">
 <!ENTITY lol7 "&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;&lol6;">
 <!ENTITY lol8 "&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;&lol7;">
 <!ENTITY lol9 "&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;&lol8;">
]>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>&lol9;</name>
<Point><coordinates>77.5,12.9</coordinates></Point></Placemark></Document></kml>"""

EXTERNAL_ENTITY = b"""<?xml version="1.0"?>
<!DOCTYPE x [ <!ENTITY secret SYSTEM "file:///etc/passwd"> ]>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>&secret;</name>
<Point><coordinates>77.5,12.9</coordinates></Point></Placemark></Document></kml>"""


@pytest.fixture
def client(make_client):
    return make_client(files.router)


def post(client, data, name):
    return client.post("/api/files/", files={"file": (name, data)})


def test_entity_expansion_kml_is_safe_and_fast(client):
    start = time.perf_counter()
    r = post(client, BILLION_LAUGHS, "bomb.kml")
    assert time.perf_counter() - start < 10
    assert r.status_code in (201, 422)
    if r.status_code == 201:  # if accepted, the expanded text must not have exploded memory
        fid = r.json()["id"]
        body = client.get(f"/api/files/{fid}/measurements/").text
        assert len(body) < 1_000_000


def test_external_entity_is_not_resolved(client):
    r = post(client, EXTERNAL_ENTITY, "xxe.kml")
    text = r.text
    if r.status_code == 201:
        text += client.get(f"/api/files/{r.json()['id']}/measurements/").text
    assert "root:" not in text and "/bin/" not in text


def test_zip_with_thousands_of_entries_rejected_fast(client, tmp_path):
    z = make_zip(tmp_path / "many.zip", {f"f{i}.txt": b"x" for i in range(5000)})
    start = time.perf_counter()
    r = post(client, z.read_bytes(), "many.zip")
    assert time.perf_counter() - start < 5
    assert r.status_code == 422 and "too many" in r.json()["error"]["message"]


def test_highly_compressible_zip_bomb_rejected(client, settings, tmp_path):
    settings.max_uncompressed_mb = 5
    z = make_zip(tmp_path / "bomb.zip", {"data.shp": b"0" * (50 * 1024 * 1024)})
    assert z.stat().st_size < 200_000
    r = post(client, z.read_bytes(), "bomb.zip")
    assert r.status_code == 422 and "too large" in r.json()["error"]["message"]


def test_absolute_path_member_rejected(client, tmp_path):
    z = make_zip(tmp_path / "abs.zip", {"/tmp/evil.shp": b"x", "data.shp": b"x"})
    r = post(client, z.read_bytes(), "abs.zip")
    assert r.status_code == 422 and "unsafe" in r.json()["error"]["message"]


def test_normal_shapefile_still_accepted(client, tmp_path):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "ok.zip")
    assert post(client, z.read_bytes(), "ok.zip").status_code == 201
