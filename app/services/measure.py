"""Area and length of features, always measured in a projected (UTM) CRS, never in degrees.

Flow:
1. Convert all geometries to EPSG:4326 once.
2. For each feature (for multi-part geometries, each part) pick the UTM zone from the centre
   of its bounding box.
3. Transform to that zone and read .area or .length (square meters, meters), summing parts.
Every feature is handled on its own, so one bad feature never affects the others.
"""

import logging
import math

import geopandas as gpd
import shapely
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.validation import explain_validity

from app.errors import UnprocessableFile
from app.models import MeasurementStatus
from app.services.types import FeatureMeasurement

logger = logging.getLogger(__name__)

POINT_TYPES = {"Point", "MultiPoint"}
LINE_TYPES = {"LineString", "MultiLineString"}
POLYGON_TYPES = {"Polygon", "MultiPolygon"}
MIN_UTM_LATITUDE = -80.0
MAX_UTM_LATITUDE = 84.0


def utm_epsg_for(lon: float, lat: float) -> int | None:
    """EPSG code of the UTM zone for a lon/lat, or None outside the UTM latitude range."""
    if not (MIN_UTM_LATITUDE <= lat <= MAX_UTM_LATITUDE):
        return None
    zone = min(max(math.floor((lon + 180) / 6) + 1, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


class _TransformerCache:
    """One WGS84 -> UTM transformer per zone, created lazily for a single measuring run.

    always_xy=True is essential: without it pyproj expects (lat, lon) for EPSG:4326.
    """

    def __init__(self) -> None:
        self._items: dict[int, Transformer] = {}

    def get(self, epsg: int) -> Transformer:
        if epsg not in self._items:
            self._items[epsg] = Transformer.from_crs(4326, epsg, always_xy=True)
        return self._items[epsg]


def _project(geom: BaseGeometry, cache: _TransformerCache, epsg: int) -> BaseGeometry:
    return transform(cache.get(epsg).transform, geom)


def measure_features(gdf: gpd.GeoDataFrame) -> list[FeatureMeasurement]:
    """Measure every row of `gdf` (which must have a CRS). Result order matches row order."""
    try:
        geographic = gdf if gdf.crs.to_epsg() == 4326 else gdf.to_crs(4326)
    except Exception as exc:
        logger.warning("CRS transformation to EPSG:4326 failed: %s", exc)
        raise UnprocessableFile(
            "The file's coordinate reference system could not be converted to WGS84."
        ) from exc

    cache = _TransformerCache()
    results: list[FeatureMeasurement] = []
    for position, geom in enumerate(geographic.geometry):
        try:
            results.append(_measure_one(geom, cache))
        except Exception as exc:  # isolate: one bad feature must not stop the rest
            logger.warning("Measuring feature %s failed: %s", position, type(exc).__name__)
            results.append(
                FeatureMeasurement(
                    MeasurementStatus.INVALID, message=f"Measurement failed: {type(exc).__name__}"
                )
            )
    return results


def _measure_one(geom: BaseGeometry | None, cache: _TransformerCache) -> FeatureMeasurement:
    if geom is None or geom.is_empty:
        return FeatureMeasurement(MeasurementStatus.INVALID, message="Missing or empty geometry.")

    geom_type = geom.geom_type
    if geom_type in POINT_TYPES:
        return FeatureMeasurement(
            MeasurementStatus.NOT_APPLICABLE, message="Points have no measurement."
        )
    if geom_type not in POLYGON_TYPES | LINE_TYPES:
        return FeatureMeasurement(
            MeasurementStatus.UNSUPPORTED,
            message=f"Geometry type {geom_type} is not supported for measurement.",
        )

    minx, miny, maxx, maxy = geom.bounds
    if not all(math.isfinite(value) for value in (minx, miny, maxx, maxy)):
        return FeatureMeasurement(
            MeasurementStatus.INVALID, message="Coordinates are not finite numbers."
        )
    if abs(minx) > 180 or abs(maxx) > 180 or abs(miny) > 90 or abs(maxy) > 90:
        return FeatureMeasurement(
            MeasurementStatus.INVALID,
            message="Coordinates are outside the valid longitude and latitude range.",
        )
    if not geom.is_valid:
        return FeatureMeasurement(
            MeasurementStatus.INVALID, message=f"Invalid geometry: {explain_validity(geom)}"
        )

    # Multi-part geometries are measured part by part, each in the UTM zone of its own
    # location, so far apart parts (for example France and French Guiana) stay accurate.
    parts = list(geom.geoms) if geom_type.startswith("Multi") else [geom]
    is_area = geom_type in POLYGON_TYPES
    total = 0.0
    zones: set[int] = set()
    for part in parts:
        if part.is_empty:
            continue
        part_minx, part_miny, part_maxx, part_maxy = part.bounds
        epsg = utm_epsg_for((part_minx + part_maxx) / 2, (part_miny + part_maxy) / 2)
        if epsg is None:
            return FeatureMeasurement(
                MeasurementStatus.UNSUPPORTED,
                message="Location is outside UTM coverage (latitude below -80 or above 84).",
            )
        projected = _project(shapely.force_2d(part), cache, epsg)
        total += projected.area if is_area else projected.length
        zones.add(epsg)

    measurement_crs = ",".join(f"EPSG:{epsg}" for epsg in sorted(zones))
    if is_area:
        return FeatureMeasurement(
            MeasurementStatus.MEASURED, area_m2=total, measurement_crs=measurement_crs
        )
    return FeatureMeasurement(
        MeasurementStatus.MEASURED, length_m=total, measurement_crs=measurement_crs
    )
