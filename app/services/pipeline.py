"""The whole upload flow: save, record, read, measure, persist, finalize."""

import logging
import tempfile
import time
from collections import Counter
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import Feature, File, FileStatus, FileType
from app.services.measure import measure_features
from app.services.reader import read_geodata
from app.services.serialization import geometry_to_geojson, to_json_safe
from app.services.types import FeatureMeasurement, ParsedGeoFile, SavedUpload
from app.services.upload import extract_shapefile_zip, save_upload

logger = logging.getLogger(__name__)

GENERIC_FAILURE = "Internal error while processing the file."


def process_upload(db: Session, upload: UploadFile, settings: Settings) -> File:
    """Process one upload end to end and return the stored File.

    Problems found while saving the upload (size, type, empty) raise before any record exists.
    Problems found while reading the content create a FAILED record and raise with its file_id.
    """
    started = time.perf_counter()
    # ignore_cleanup_errors: on Windows a library may briefly keep a handle on a temp file.
    with tempfile.TemporaryDirectory(prefix="geo_upload_", ignore_cleanup_errors=True) as tmp:
        work_dir = Path(tmp)
        saved = save_upload(upload, work_dir, settings.max_upload_bytes)

        file = File(
            filename=saved.filename,
            file_type=saved.file_type,
            status=FileStatus.PROCESSING,
            size_bytes=saved.size_bytes,
        )
        db.add(file)
        db.commit()
        file_id = file.id

        try:
            statuses = _read_measure_store(db, file, saved, work_dir, settings)
        except Exception as exc:
            db.rollback()
            _mark_failed(db, file_id, exc)
            if isinstance(exc, AppError):
                exc.file_id = file_id
            raise

    logger.info(
        "Processed file id=%s type=%s size=%d features=%d statuses=%s duration_ms=%d",
        file_id,
        saved.file_type,
        saved.size_bytes,
        file.feature_count,
        dict(statuses),
        (time.perf_counter() - started) * 1000,
    )
    return file


def _read_measure_store(
    db: Session, file: File, saved: SavedUpload, work_dir: Path, settings: Settings
) -> Counter:
    dataset_path = saved.path
    if saved.file_type == FileType.SHAPEFILE:
        extract_dir = work_dir / "shapefile"
        extract_dir.mkdir()
        dataset_path = extract_shapefile_zip(
            saved.path, extract_dir, settings.max_uncompressed_bytes, settings.max_zip_entries
        )

    parsed = read_geodata(dataset_path, saved.file_type, settings.max_features)
    measurements = measure_features(parsed.gdf)
    rows = _build_feature_rows(file.id, parsed, measurements)

    db.execute(insert(Feature), rows)
    file.crs = parsed.crs
    file.feature_count = len(rows)
    file.status = FileStatus.COMPLETED
    db.commit()
    return Counter(m.status for m in measurements)


def _build_feature_rows(
    file_id: str, parsed: ParsedGeoFile, measurements: list[FeatureMeasurement]
) -> list[dict]:
    gdf = parsed.gdf
    geometry_column = gdf.geometry.name
    property_columns = [column for column in gdf.columns if column != geometry_column]
    properties = gdf[property_columns].to_dict("records")

    rows = []
    for index, (geom, props, measurement) in enumerate(
        zip(gdf.geometry, properties, measurements, strict=True)
    ):
        rows.append(
            {
                "file_id": file_id,
                "feature_index": index,
                "geometry_type": None if geom is None else geom.geom_type,
                "geometry": geometry_to_geojson(geom),
                "properties": to_json_safe(props),
                "measurement_status": measurement.status,
                "area_m2": measurement.area_m2,
                "length_m": measurement.length_m,
                "measurement_crs": measurement.measurement_crs,
                "measurement_message": measurement.message,
            }
        )
    return rows


def _mark_failed(db: Session, file_id: str, exc: Exception) -> None:
    if isinstance(exc, AppError):
        message = exc.message
        logger.warning("File %s failed: %s", file_id, message)
    else:
        message = GENERIC_FAILURE
        logger.error("File %s failed unexpectedly", file_id, exc_info=exc)
    try:
        file = db.get(File, file_id)
        file.status = FileStatus.FAILED
        file.error_message = message
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record failure for file %s", file_id)
