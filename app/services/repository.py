"""Small database query helpers."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import FileNotFound
from app.models import Feature, File


def get_file(db: Session, file_id: str) -> File:
    file = db.get(File, file_id)
    if file is None:
        raise FileNotFound("File not found.")
    return file


def count_features(db: Session, file_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Feature).where(Feature.file_id == file_id))


def list_features(db: Session, file_id: str, limit: int, offset: int) -> list[Feature]:
    statement = (
        select(Feature)
        .where(Feature.file_id == file_id)
        .order_by(Feature.feature_index)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement))
