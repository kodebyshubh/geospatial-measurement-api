"""ORM models: File (one upload) and Feature (one geometry in that upload)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import DateTime as SADateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class FileType:
    KML = "KML"
    SHAPEFILE = "SHAPEFILE"


class FileStatus:
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementStatus:
    MEASURED = "MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC)


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=FileStatus.PROCESSING)
    crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(SADateTime(timezone=True), default=_utcnow)

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Feature.feature_index",
    )


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("file_id", "feature_index", name="uq_feature_file_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    feature_index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    measurement_status: Mapped[str] = mapped_column(String(16))
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(Text, nullable=True)
    measurement_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped[File] = relationship(back_populates="features")
