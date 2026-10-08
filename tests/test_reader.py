import pytest

from app.errors import UnprocessableFile
from app.models import FileType
from app.services.reader import crs_to_string, read_geodata
from app.services.upload import extract_shapefile_zip
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
    write_shapefile_zip,
)

MB = 1024 * 1024


def _read_shapefile(gdf, tmp_path, max_features=1000, **zip_kw):
    z = write_shapefile_zip(gdf, tmp_path / "s.zip", **zip_kw)
    out = tmp_path / "x"
    out.mkdir()
    shp = extract_shapefile_zip(z, out, 50 * MB, 20)
    return read_geodata(shp, FileType.SHAPEFILE, max_features)


def _read_kml(text, tmp_path, max_features=1000):
    path = tmp_path / "a.kml"
    path.write_text(text, encoding="utf-8")
    return read_geodata(path, FileType.KML, max_features)


@pytest.mark.parametrize(
    ("epsg", "expected"), [(4326, "EPSG:4326"), (32643, "EPSG:32643"), (2263, "EPSG:2263")]
)
def test_shapefile_crs_string(tmp_path, epsg, expected):
    gdf = make_gdf([square(77.5, 12.9)], crs=4326, name=["a"]).to_crs(epsg)
    parsed = _read_shapefile(gdf, tmp_path)
    assert parsed.crs == expected
    assert len(parsed.gdf) == 1 and parsed.gdf.loc[0, "name"] == "a"


def test_shapefile_keeps_null_geometry_row_and_order(tmp_path):
    gdf = make_gdf([square(77.5, 12.9), None, square(77.6, 12.9)], name=["a", "b", "c"])
    parsed = _read_shapefile(gdf, tmp_path)
    assert list(parsed.gdf["name"]) == ["a", "b", "c"]
    assert parsed.gdf.geometry.iloc[1] is None
    assert list(parsed.gdf.index) == [0, 1, 2]


def test_shapefile_without_prj_is_rejected_by_reader_too(tmp_path):
    # Bypass the extractor check to prove the reader alone also refuses an unknown CRS.
    gdf = make_gdf([square(77.5, 12.9)])
    gdf.to_file(tmp_path / "data.shp")
    (tmp_path / "data.prj").unlink()
    with pytest.raises(UnprocessableFile, match="coordinate reference system"):
        read_geodata(tmp_path / "data.shp", FileType.SHAPEFILE, 100)


def test_shapefile_too_many_features(tmp_path):
    gdf = make_gdf([square(77.5 + i * 0.1, 12.9) for i in range(5)])
    with pytest.raises(UnprocessableFile, match="more than 3"):
        _read_shapefile(gdf, tmp_path, max_features=3)


def test_corrupt_shapefile(tmp_path):
    for ext in ("shp", "shx", "dbf", "prj"):
        (tmp_path / f"data.{ext}").write_bytes(b"garbage garbage garbage")
    with pytest.raises(UnprocessableFile, match="could not be read"):
        read_geodata(tmp_path / "data.shp", FileType.SHAPEFILE, 100)


def test_shapefile_with_no_features(tmp_path):
    gdf = make_gdf([square(77.5, 12.9)]).iloc[0:0]
    with pytest.raises(UnprocessableFile, match="no features"):
        _read_shapefile(gdf, tmp_path)


def test_kml_nested_folders_mixed_geometry(tmp_path):
    text = kml_document(
        placemark("loose", point_xml((77.5, 12.9, 5))),
        folder(
            "Parcels",
            placemark(
                "Plot A",
                polygon_xml(
                    closed_square(77.5, 12.9),
                    holes=[
                        [(77.503, 12.903), (77.505, 12.903), (77.505, 12.905), (77.503, 12.905)]
                        + [(77.503, 12.903)]
                    ],
                ),
                data={"owner": "Ravi"},
            ),
            folder("Nested", placemark("Road", linestring_xml([(77.5, 12.9), (77.51, 12.91)]))),
        ),
        folder("Empty"),
    )
    parsed = _read_kml(text, tmp_path)
    assert parsed.crs == "EPSG:4326"
    assert parsed.gdf.crs.to_epsg() == 4326
    assert len(parsed.gdf) == 3
    assert sorted(parsed.gdf["Name"]) == ["Plot A", "Road", "loose"]
    types = dict(zip(parsed.gdf["Name"], parsed.gdf.geometry.geom_type, strict=True))
    assert types == {"loose": "Point", "Plot A": "Polygon", "Road": "LineString"}
    # style noise removed, real ExtendedData kept
    for noise in ("tessellate", "extrude", "visibility"):
        assert noise not in parsed.gdf.columns
    assert "owner" in parsed.gdf.columns
    assert parsed.gdf.set_index("Name").loc["Plot A", "owner"] == "Ravi"
    assert list(parsed.gdf.index) == [0, 1, 2]


def test_kml_folders_with_the_same_name_are_both_read(tmp_path):
    text = kml_document(
        folder("Same", placemark("one", point_xml((77.5, 12.9)))),
        folder("Same", placemark("two", point_xml((77.6, 12.9)))),
    )
    parsed = _read_kml(text, tmp_path)
    assert sorted(parsed.gdf["Name"]) == ["one", "two"]


def test_kml_multigeometry_becomes_collection(tmp_path):
    multi = (
        "<MultiGeometry>"
        + polygon_xml(closed_square(77.5, 12.9))
        + point_xml((77.7, 12.9))
        + "</MultiGeometry>"
    )
    parsed = _read_kml(kml_document(placemark("m", multi)), tmp_path)
    assert parsed.gdf.geometry.iloc[0].geom_type == "GeometryCollection"


def test_kml_without_placemarks(tmp_path):
    with pytest.raises(UnprocessableFile, match="no features"):
        _read_kml(kml_document(folder("Empty")), tmp_path)


def test_malformed_kml(tmp_path):
    with pytest.raises(UnprocessableFile):
        _read_kml("<kml><Document><Placemark><name>x</name>", tmp_path)


def test_kml_too_many_features(tmp_path):
    text = kml_document(*[placemark(f"p{i}", point_xml((77.5 + i / 100, 12.9))) for i in range(5)])
    with pytest.raises(UnprocessableFile, match="more than 3"):
        _read_kml(text, tmp_path, max_features=3)


def test_crs_to_string_fallbacks():
    from pyproj import CRS

    assert crs_to_string(CRS.from_epsg(4326)) == "EPSG:4326"
    custom = CRS.from_proj4("+proj=tmerc +lat_0=1 +lon_0=2 +k=1 +x_0=0 +y_0=0 +datum=WGS84")
    assert crs_to_string(custom)  # never empty, falls back to authority or name
