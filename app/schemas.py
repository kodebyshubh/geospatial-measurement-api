"""Pydantic response models. Field names match the API contract shown in the README."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    status: str
    crs: str | None
    feature_count: int
    error_message: str | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _assume_utc(cls, value: datetime) -> datetime:
        # SQLite returns naive datetimes. Everything is stored in UTC.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class MeasurementOut(BaseModel):
    status: str
    area_m2: float | None
    length_m: float | None
    measurement_crs: str | None
    message: str | None


class FeatureOut(BaseModel):
    index: int
    geometry_type: str | None
    crs: str | None
    properties: dict[str, Any]
    measurement: MeasurementOut
    # Only set (and therefore only serialized) when include_geometry=true.
    geometry: dict[str, Any] | None = None


class MeasurementsPage(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    features: list[FeatureOut]


class ErrorBody(BaseModel):
    code: str
    message: str
    file_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
