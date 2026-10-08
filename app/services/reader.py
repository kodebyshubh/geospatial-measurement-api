"""Reading a Shapefile or a KML into a GeoDataFrame and working out its CRS."""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
from pyproj import CRS

from app.errors import AppError, UnprocessableFile
from app.models import FileType
from app.services.types import ParsedGeoFile

logger = logging.getLogger(__name__)

# KML columns GDAL always adds with constant style defaults. They are not real attributes.
KML_STYLE_COLUMNS = ["tessellate", "extrude", "visibility"]
WGS84 = "EPSG:4326"


def crs_to_string(crs: CRS) -> str:
    """EPSG code if there is one, else authority:code, else the CRS name."""
    epsg = crs.to_epsg()
    if epsg:
        return f"EPSG:{epsg}"
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name


def read_geodata(path: Path, file_type: str, max_features: int) -> ParsedGeoFile:
    """Read the dataset at `path`. Raises UnprocessableFile for anything unreadable."""
    try:
        if file_type == FileType.SHAPEFILE:
            gdf, crs = _read_shapefile(path, max_features)
        else:
            gdf, crs = _read_kml(path)
    except AppError:
        raise
    except Exception as exc:
        logger.warning("Could not read %s file: %s", file_type, exc)
        kind = "Shapefile" if file_type == FileType.SHAPEFILE else "KML"
        raise UnprocessableFile(f"The file could not be read as a valid {kind}.") from exc

    if len(gdf) == 0:
        raise UnprocessableFile("The file contains no features.")
    if len(gdf) > max_features:
        raise UnprocessableFile(f"The file has more than {max_features} features (the limit).")
    return ParsedGeoFile(crs=crs, gdf=gdf.reset_index(drop=True))


def _read_shapefile(path: Path, max_features: int) -> tuple[gpd.GeoDataFrame, str]:
    count = pyogrio.read_info(path)["features"]
    if count > max_features:
        raise UnprocessableFile(f"The file has more than {max_features} features (the limit).")
    gdf = gpd.read_file(path, engine="pyogrio")
    if gdf.crs is None:
        raise UnprocessableFile(
            "Shapefile has no .prj file, so its coordinate reference system is unknown."
        )
    return gdf, crs_to_string(gdf.crs)


def _read_kml(path: Path) -> tuple[gpd.GeoDataFrame, str]:
    # GDAL makes one layer per KML Folder. Read by position because folder names can repeat.
    layer_count = len(pyogrio.list_layers(path))
    frames: list[gpd.GeoDataFrame] = []
    for position in range(layer_count):
        layer = gpd.read_file(path, engine="pyogrio", layer=position)
        if layer.empty:
            continue
        layer = layer.drop(columns=KML_STYLE_COLUMNS, errors="ignore")
        non_geometry = [column for column in layer.columns if column != layer.geometry.name]
        all_null = [column for column in non_geometry if layer[column].isna().all()]
        frames.append(layer.drop(columns=all_null))

    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=WGS84), WGS84
    combined = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs=WGS84), WGS84
