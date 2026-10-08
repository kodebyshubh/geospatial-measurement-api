"""Turning pandas, numpy and shapely values into plain JSON safe Python values."""

import json
import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry


def to_json_safe(value: Any) -> Any:
    """Convert a value so that json.dumps(..., allow_nan=False) accepts it."""
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, bool | str):
        return value
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return to_json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, datetime | date):  # includes pandas Timestamp
        return value.isoformat()
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | np.ndarray):
        return [to_json_safe(item) for item in value]
    return str(value)


def geometry_to_geojson(geom: BaseGeometry | None) -> dict | None:
    """GeoJSON style dict in the geometry's own coordinates, or None when there is no geometry."""
    if geom is None:
        return None
    return json.loads(shapely.to_geojson(geom))
