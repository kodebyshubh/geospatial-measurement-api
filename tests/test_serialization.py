import datetime as dt
import json

import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from app.services.serialization import geometry_to_geojson, to_json_safe


def test_basic_values():
    assert to_json_safe(None) is None
    assert to_json_safe("é 名前") == "é 名前"
    assert to_json_safe(True) is True
    assert to_json_safe(3) == 3
    assert to_json_safe(2.5) == 2.5


def test_nan_inf_nat_na_become_none():
    for value in (
        float("nan"),
        float("inf"),
        np.float64("nan"),
        pd.NaT,
        pd.NA,
        np.datetime64("NaT"),
    ):
        assert to_json_safe(value) is None


def test_numpy_scalars():
    assert to_json_safe(np.int64(7)) == 7 and type(to_json_safe(np.int64(7))) is int
    assert to_json_safe(np.float32(1.5)) == 1.5
    assert to_json_safe(np.bool_(True)) is True


def test_dates_and_timestamps():
    assert to_json_safe(pd.Timestamp("2020-01-02 03:04:05")) == "2020-01-02T03:04:05"
    assert to_json_safe(dt.date(2020, 1, 2)) == "2020-01-02"
    assert to_json_safe(np.datetime64("2020-01-02T03:04:05")) == "2020-01-02T03:04:05"


def test_bytes_and_nested_containers_and_unknown_objects():
    assert to_json_safe(b"abc") == "abc"
    assert to_json_safe(b"\xff") == "\ufffd"
    value = {
        "a": [1, np.int64(2), {"b": float("nan")}],
        3: (1, 2),
        "s": {
            1,
        },
    }
    out = to_json_safe(value)
    assert out == {"a": [1, 2, {"b": None}], "3": [1, 2], "s": [1]}
    assert to_json_safe(complex(1, 2)) == "(1+2j)"


def test_everything_survives_strict_json():
    mixed = [np.nan, np.int64(1), pd.Timestamp("2020-01-01"), b"x", {"k": pd.NaT}, "é"]
    json.dumps(to_json_safe(mixed), allow_nan=False)


def test_geometry_to_geojson():
    assert geometry_to_geojson(None) is None
    assert geometry_to_geojson(Point(1, 2)) == {"type": "Point", "coordinates": [1.0, 2.0]}
    line = geometry_to_geojson(LineString([(0, 0), (1, 1)]))
    assert line["type"] == "LineString" and line["coordinates"] == [[0.0, 0.0], [1.0, 1.0]]
    poly = geometry_to_geojson(Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]))
    assert poly["type"] == "Polygon" and isinstance(poly["coordinates"][0], list)
