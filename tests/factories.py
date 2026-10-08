"""Helpers that build test data in code: GeoDataFrames, shapefile zips, KML text, raw zips."""

import io
import zipfile
from pathlib import Path

import geopandas as gpd
from fastapi import UploadFile
from shapely.geometry import box


def make_gdf(geoms, crs=4326, **columns) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns, geometry=list(geoms), crs=crs)


def square(lon: float, lat: float, size: float = 0.01):
    return box(lon, lat, lon + size, lat + size)


def write_shapefile_zip(
    gdf: gpd.GeoDataFrame,
    path: Path,
    include_prj: bool = True,
    nested_folder: bool = False,
    drop_parts: tuple[str, ...] = (),
) -> Path:
    """Write gdf as a Shapefile into a temp folder, then zip the parts at `path`."""
    folder = path.parent / f"_{path.stem}_parts"
    folder.mkdir(exist_ok=True)
    gdf.to_file(folder / "data.shp")
    prefix = "survey/data/" if nested_folder else ""
    with zipfile.ZipFile(path, "w") as archive:
        for part in sorted(folder.iterdir()):
            if part.suffix == ".prj" and not include_prj:
                continue
            if part.suffix in drop_parts:
                continue
            archive.write(part, prefix + part.name)
    return path


def make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    """Zip with arbitrary member names (used for zip slip and bomb style cases)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def upload_file(data: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename)


# KML builders ---------------------------------------------------------------


def coords_xml(points) -> str:
    return " ".join(",".join(str(v) for v in point) for point in points)


def polygon_xml(outer, holes=()) -> str:
    inner = "".join(
        f"<innerBoundaryIs><LinearRing><coordinates>{coords_xml(h)}</coordinates>"
        "</LinearRing></innerBoundaryIs>"
        for h in holes
    )
    return (
        "<Polygon><outerBoundaryIs><LinearRing>"
        f"<coordinates>{coords_xml(outer)}</coordinates>"
        f"</LinearRing></outerBoundaryIs>{inner}</Polygon>"
    )


def linestring_xml(points) -> str:
    return f"<LineString><coordinates>{coords_xml(points)}</coordinates></LineString>"


def point_xml(point) -> str:
    return f"<Point><coordinates>{coords_xml([point])}</coordinates></Point>"


def placemark(name: str, geometry_xml: str, data: dict | None = None) -> str:
    extended = ""
    if data:
        items = "".join(f'<Data name="{k}"><value>{v}</value></Data>' for k, v in data.items())
        extended = f"<ExtendedData>{items}</ExtendedData>"
    return f"<Placemark><name>{name}</name>{extended}{geometry_xml}</Placemark>"


def folder(name: str, *children: str) -> str:
    return f"<Folder><name>{name}</name>{''.join(children)}</Folder>"


def kml_document(*children: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Test</name>'
        f"{''.join(children)}</Document></kml>"
    )


def closed_square(lon: float, lat: float, size: float = 0.01):
    return [
        (lon, lat),
        (lon + size, lat),
        (lon + size, lat + size),
        (lon, lat + size),
        (lon, lat),
    ]
