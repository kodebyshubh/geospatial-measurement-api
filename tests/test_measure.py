import math

import pytest
from pyproj import Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    box,
)

from app.models import MeasurementStatus as S
from app.services import measure
from app.services.measure import measure_features, utm_epsg_for
from tests.factories import make_gdf, square

GEOD = Geod(ellps="WGS84")


def geod_area(poly) -> float:
    return abs(GEOD.geometry_area_perimeter(poly)[0])


def rel_diff(a: float, b: float) -> float:
    return abs(a - b) / b


@pytest.mark.parametrize(
    ("lon", "lat", "expected"),
    [
        (77.59, 12.97, 32643),
        (-122.4, 37.8, 32610),
        (151.2, -33.9, 32756),
        (180.0, 10.0, 32660),
        (-180.0, 10.0, 32601),
        (0.0, 0.0, 32631),
        (10.0, 84.0, 32632),
        (10.0, -80.0, 32732),
        (10.0, 85.0, None),
        (10.0, -81.0, None),
    ],
)
def test_utm_epsg_for(lon, lat, expected):
    assert utm_epsg_for(lon, lat) == expected


@pytest.mark.parametrize(
    "origin", [(77.59, 12.97), (36.8, 0.01), (151.2, -33.9), (10.7, 59.9), (-122.4, 37.8)]
)
def test_polygon_area_matches_geodesic_reference(origin):
    poly = square(*origin, size=0.02)
    [m] = measure_features(make_gdf([poly]))
    assert m.status == S.MEASURED and m.length_m is None
    assert rel_diff(m.area_m2, geod_area(poly)) < 0.005


def test_line_length_matches_geodesic_reference():
    line = LineString([(77.59, 12.97), (77.62, 12.99), (77.65, 12.97)])
    [m] = measure_features(make_gdf([line]))
    assert m.status == S.MEASURED and m.area_m2 is None
    assert rel_diff(m.length_m, GEOD.geometry_length(line)) < 0.005


def test_not_computed_in_degrees():
    [m] = measure_features(make_gdf([box(0, 0, 0.01, 0.01)]))
    assert 1_000_000 < m.area_m2 < 2_000_000  # 0.01 degree square is about 1.2 km2


def test_projected_input_100m_square():
    gdf = make_gdf([box(500000, 1435000, 500100, 1435100)], crs=32643)
    [m] = measure_features(gdf)
    assert m.area_m2 == pytest.approx(10_000, rel=1e-3)
    assert m.measurement_crs == "EPSG:32643"


def test_feet_based_crs_returns_square_meters():
    gdf = make_gdf([box(1_000_000, 200_000, 1_000_100, 200_100)], crs=2263)  # 100 ft square
    [m] = measure_features(gdf)
    assert m.area_m2 == pytest.approx(100 * 100 * 0.3048**2, rel=3e-3)


def test_polygon_with_hole_excludes_hole():
    outer = [(77.5, 12.9), (77.51, 12.9), (77.51, 12.91), (77.5, 12.91)]
    hole = [(77.503, 12.903), (77.507, 12.903), (77.507, 12.907), (77.503, 12.907)]
    holed = Polygon(outer, [hole])
    [with_hole] = measure_features(make_gdf([holed]))
    [solid] = measure_features(make_gdf([Polygon(outer)]))
    [hole_only] = measure_features(make_gdf([Polygon(hole)]))
    assert with_hole.area_m2 == pytest.approx(solid.area_m2 - hole_only.area_m2, rel=1e-9)


def test_multi_parts_are_summed():
    a, b = square(77.5, 12.9), square(77.6, 12.9)
    [multi] = measure_features(make_gdf([MultiPolygon([a, b])]))
    [ma], [mb] = measure_features(make_gdf([a])), measure_features(make_gdf([b]))
    assert multi.area_m2 == pytest.approx(ma.area_m2 + mb.area_m2, rel=1e-6)

    l1, l2 = LineString([(77.5, 12.9), (77.51, 12.9)]), LineString([(77.6, 12.9), (77.6, 12.91)])
    [ml] = measure_features(make_gdf([MultiLineString([l1, l2])]))
    [m1], [m2] = measure_features(make_gdf([l1])), measure_features(make_gdf([l2]))
    assert ml.length_m == pytest.approx(m1.length_m + m2.length_m, rel=1e-6)


def test_points_not_applicable():
    for geom in (Point(77.5, 12.9), MultiPoint([(77.5, 12.9), (77.6, 12.9)])):
        [m] = measure_features(make_gdf([geom]))
        assert m.status == S.NOT_APPLICABLE and m.area_m2 is None and m.length_m is None
        assert m.measurement_crs is None and m.message


def test_collection_unsupported():
    [m] = measure_features(make_gdf([GeometryCollection([Point(77.5, 12.9), square(77.5, 12.9)])]))
    assert m.status == S.UNSUPPORTED and "GeometryCollection" in m.message


def test_null_and_empty_geometry_invalid():
    ms = measure_features(make_gdf([None, Polygon()]))
    assert [m.status for m in ms] == [S.INVALID, S.INVALID]
    assert all("empty" in m.message.lower() for m in ms)


def test_bow_tie_polygon_invalid_with_reason():
    bow = Polygon([(77.5, 12.9), (77.51, 12.91), (77.51, 12.9), (77.5, 12.91)])
    [m] = measure_features(make_gdf([bow]))
    assert m.status == S.INVALID and "Self-intersection" in m.message
    assert m.area_m2 is None


def test_polar_latitude_unsupported():
    [m] = measure_features(make_gdf([box(10, 85.5, 10.01, 85.51)]))
    assert m.status == S.UNSUPPORTED and "UTM" in m.message


def test_out_of_range_coordinates_invalid():
    [m] = measure_features(make_gdf([box(10, 10, 10.1, 95)]))
    assert m.status == S.INVALID and "range" in m.message


def test_nan_coordinates_invalid():
    [m] = measure_features(make_gdf([LineString([(77.5, 12.9), (math.nan, 12.9)])]))
    assert m.status == S.INVALID


def test_z_values_are_ignored():
    flat = Polygon([(77.5, 12.9), (77.51, 12.9), (77.51, 12.91), (77.5, 12.91)])
    tall = Polygon([(77.5, 12.9, 500), (77.51, 12.9, 900), (77.51, 12.91, 10), (77.5, 12.91, 0)])
    [a], [b] = measure_features(make_gdf([flat])), measure_features(make_gdf([tall]))
    assert a.area_m2 == pytest.approx(b.area_m2, rel=1e-12)


def test_features_in_different_zones_each_use_their_own():
    ms = measure_features(
        make_gdf([square(77.6, 12.9), square(-122.4, 37.8), square(151.2, -33.9)])
    )
    assert [m.measurement_crs for m in ms] == ["EPSG:32643", "EPSG:32610", "EPSG:32756"]


def test_results_keep_row_order_with_mixed_features():
    gdf = make_gdf(
        [square(77.5, 12.9), Point(77.5, 12.9), None, LineString([(77.5, 12.9), (77.51, 12.9)])]
    )
    assert [m.status for m in measure_features(gdf)] == [
        S.MEASURED,
        S.NOT_APPLICABLE,
        S.INVALID,
        S.MEASURED,
    ]


def test_one_failing_feature_does_not_affect_neighbours(monkeypatch):
    real_project = measure._project
    bad = square(10.0, 10.0)

    def flaky(geom, cache, epsg):
        if geom.equals(bad):
            raise RuntimeError("boom")
        return real_project(geom, cache, epsg)

    monkeypatch.setattr(measure, "_project", flaky)
    ms = measure_features(make_gdf([square(77.5, 12.9), bad, square(77.6, 12.9)]))
    assert [m.status for m in ms] == [S.MEASURED, S.INVALID, S.MEASURED]
    assert "RuntimeError" in ms[1].message


def test_multipolygon_parts_are_measured_in_their_own_zones():
    india, guiana = square(77.6, 12.9, 0.02), square(-52.9, 4.9, 0.02)
    [m] = measure_features(make_gdf([MultiPolygon([india, guiana])]))
    expected = geod_area(india) + geod_area(guiana)
    assert m.status == S.MEASURED
    assert rel_diff(m.area_m2, expected) < 0.005
    assert m.measurement_crs == "EPSG:32622,EPSG:32643"


def test_multipart_in_one_zone_reports_a_single_crs():
    [m] = measure_features(make_gdf([MultiPolygon([square(77.6, 12.9), square(77.7, 12.9)])]))
    assert m.measurement_crs == "EPSG:32643"


def test_multilinestring_parts_in_different_zones():
    a = LineString([(77.6, 12.9), (77.62, 12.9)])
    b = LineString([(-52.9, 4.9), (-52.88, 4.9)])
    [m] = measure_features(make_gdf([MultiLineString([a, b])]))
    assert rel_diff(m.length_m, GEOD.geometry_length(a) + GEOD.geometry_length(b)) < 0.005
    assert m.measurement_crs == "EPSG:32622,EPSG:32643"
