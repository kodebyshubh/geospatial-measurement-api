"""Small data containers passed between services."""

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd


@dataclass(frozen=True)
class SavedUpload:
    path: Path
    size_bytes: int
    file_type: str
    filename: str


@dataclass
class ParsedGeoFile:
    crs: str
    gdf: gpd.GeoDataFrame


@dataclass(frozen=True)
class FeatureMeasurement:
    status: str
    area_m2: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None
    message: str | None = None
