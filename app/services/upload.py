"""Saving an upload to disk safely, and safely extracting a zipped Shapefile."""

import logging
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import UploadFile

from app.errors import FileTooLarge, InvalidRequest, UnprocessableFile, UnsupportedFileType
from app.models import FileType
from app.services.types import SavedUpload

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
EXTENSION_TO_TYPE = {".kml": FileType.KML, ".zip": FileType.SHAPEFILE}
REQUIRED_PARTS = (".shp", ".shx", ".dbf", ".prj")
WANTED_PARTS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


def clean_filename(name: str | None) -> str:
    """Return only the base name, without any path parts or control characters."""
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    base = "".join(ch for ch in base if ch.isprintable())
    return base[:255] or "upload"


def save_upload(upload: UploadFile, dest_dir: Path, max_bytes: int) -> SavedUpload:
    """Stream the upload to a generated path, enforcing type, size and content checks."""
    filename = clean_filename(upload.filename)
    extension = Path(filename).suffix.lower()
    file_type = EXTENSION_TO_TYPE.get(extension)
    if file_type is None:
        hint = " Unzip KMZ files and upload the .kml inside." if extension == ".kmz" else ""
        raise UnsupportedFileType(
            "Only .kml files and .zip files containing a Shapefile are supported." + hint
        )

    dest = dest_dir / f"upload{extension}"
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := upload.file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLarge(
                        f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit."
                    )
                out.write(chunk)
    except FileTooLarge:
        dest.unlink(missing_ok=True)
        raise

    if size == 0:
        dest.unlink(missing_ok=True)
        raise InvalidRequest("The uploaded file is empty.")

    if not _content_matches(dest, file_type):
        dest.unlink(missing_ok=True)
        what = "a zip archive" if file_type == FileType.SHAPEFILE else "XML"
        raise UnsupportedFileType(
            f"The file extension is {extension} but the content is not {what}."
        )

    return SavedUpload(path=dest, size_bytes=size, file_type=file_type, filename=filename)


def _content_matches(path: Path, file_type: str) -> bool:
    if file_type == FileType.SHAPEFILE:
        return zipfile.is_zipfile(path)
    with open(path, "rb") as handle:
        head = handle.read(4096)
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.lstrip().startswith(b"<")


def _unsafe_member_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    drive_like = len(normalized) > 1 and normalized[1] == ":"
    return normalized.startswith("/") or drive_like or ".." in parts


def extract_shapefile_zip(
    zip_path: Path, dest_dir: Path, max_uncompressed_bytes: int, max_entries: int
) -> Path:
    """Safely extract the single Shapefile in a zip. Returns the path to the extracted .shp.

    Checks run before anything is written: entry count, total uncompressed size, unsafe
    member names (zip slip). Only the Shapefile parts are extracted, under fixed names
    (data.shp, data.dbf, ...), so archive member names never become file system paths.
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UnprocessableFile("The zip file is corrupt and cannot be opened.") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > max_entries:
            raise UnprocessableFile(f"The zip contains too many entries (limit {max_entries}).")
        if sum(info.file_size for info in infos) > max_uncompressed_bytes:
            raise UnprocessableFile("The zip is too large when uncompressed.")

        root = dest_dir.resolve()
        for info in infos:
            if _unsafe_member_name(info.filename):
                raise UnprocessableFile("The zip contains unsafe file paths and was rejected.")
            target = (root / info.filename.replace("\\", "/")).resolve()
            if not target.is_relative_to(root):
                raise UnprocessableFile("The zip contains unsafe file paths and was rejected.")

        shapefile_members = [
            info
            for info in infos
            if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() == ".shp"
        ]
        if not shapefile_members:
            raise UnprocessableFile("The zip does not contain a .shp file.")
        if len(shapefile_members) > 1:
            raise UnprocessableFile("The zip contains more than one .shp file. Upload one dataset.")

        shp = PurePosixPath(shapefile_members[0].filename.replace("\\", "/"))
        wanted: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            if info.is_dir():
                continue
            member = PurePosixPath(info.filename.replace("\\", "/"))
            same_dataset = member.parent == shp.parent and member.stem.lower() == shp.stem.lower()
            if same_dataset and member.suffix.lower() in WANTED_PARTS:
                wanted[member.suffix.lower()] = info

        if ".prj" not in wanted:
            raise UnprocessableFile(
                "Shapefile has no .prj file, so its coordinate reference system is unknown."
            )
        missing = [ext for ext in (".shx", ".dbf") if ext not in wanted]
        if missing:
            raise UnprocessableFile(f"Shapefile is missing required file(s): {', '.join(missing)}.")

        remaining = max_uncompressed_bytes
        for extension, info in wanted.items():
            with archive.open(info) as source, open(dest_dir / f"data{extension}", "wb") as out:
                copied = 0
                while chunk := source.read(CHUNK_SIZE):
                    copied += len(chunk)
                    if copied > remaining:
                        raise UnprocessableFile("The zip is too large when uncompressed.")
                    out.write(chunk)
                remaining -= copied

    logger.debug("Extracted shapefile parts: %s", sorted(wanted))
    return dest_dir / "data.shp"
