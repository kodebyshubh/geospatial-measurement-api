"""File endpoints: upload, file info, measurements."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.errors import FileNotCompleted
from app.models import Feature, FileStatus
from app.schemas import FeatureOut, FileInfo, MeasurementOut, MeasurementsPage
from app.services import repository
from app.services.pipeline import process_upload

router = APIRouter(prefix="/api/files", tags=["files"])

# These are plain `def` routes on purpose: parsing and reprojection are blocking, CPU bound
# work, and FastAPI runs `def` routes in a thread pool so the event loop stays free.


@router.post("/", response_model=FileInfo, status_code=201)
def upload_file(
    file: UploadFile,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Upload a `.kml` or a `.zip` containing a Shapefile, process it and return its info."""
    return process_upload(db, file, settings)


@router.get("/{file_id}/", response_model=FileInfo)
def get_file_info(file_id: str, db: Annotated[Session, Depends(get_db)]):
    """Status, CRS and feature count of an uploaded file."""
    return repository.get_file(db, file_id)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsPage,
    response_model_exclude_unset=True,
)
def get_measurements(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_geometry: bool = False,
):
    """Per feature measurements, ordered by feature index."""
    file = repository.get_file(db, file_id)
    if file.status != FileStatus.COMPLETED:
        raise FileNotCompleted(f"File processing is not completed (status: {file.status}).")

    total = repository.count_features(db, file_id)
    features = repository.list_features(db, file_id, limit, offset)
    return MeasurementsPage(
        file_id=file_id,
        total=total,
        limit=limit,
        offset=offset,
        features=[_feature_out(feature, file.crs, include_geometry) for feature in features],
    )


def _feature_out(feature: Feature, crs: str | None, include_geometry: bool) -> FeatureOut:
    values = {
        "index": feature.feature_index,
        "geometry_type": feature.geometry_type,
        "crs": crs,
        "properties": feature.properties or {},
        "measurement": MeasurementOut(
            status=feature.measurement_status,
            area_m2=feature.area_m2,
            length_m=feature.length_m,
            measurement_crs=feature.measurement_crs,
            message=feature.measurement_message,
        ),
    }
    if include_geometry:
        values["geometry"] = feature.geometry
    return FeatureOut(**values)
