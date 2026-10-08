import pytest

from app.errors import (
    FileTooLarge,
    InvalidRequest,
    UnprocessableFile,
    UnsupportedFileType,
)
from app.models import FileType
from app.services.upload import clean_filename, extract_shapefile_zip, save_upload
from tests.factories import (
    closed_square,
    kml_document,
    make_gdf,
    make_zip,
    placemark,
    polygon_xml,
    square,
    upload_file,
    write_shapefile_zip,
)

MB = 1024 * 1024


@pytest.fixture
def work(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


def _kml_bytes():
    return kml_document(placemark("a", polygon_xml(closed_square(77.5, 12.9)))).encode()


def test_save_valid_kml(work):
    saved = save_upload(upload_file(_kml_bytes(), "survey.KML"), work, MB)
    assert saved.file_type == FileType.KML
    assert saved.filename == "survey.KML"
    assert saved.size_bytes == len(_kml_bytes())
    assert saved.path.read_bytes() == _kml_bytes()


def test_save_valid_kml_with_bom_and_whitespace(work):
    data = b"\xef\xbb\xbf  \n" + _kml_bytes()
    assert save_upload(upload_file(data, "a.kml"), work, MB).file_type == FileType.KML


def test_save_valid_zip(work, tmp_path):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "s.zip")
    saved = save_upload(upload_file(z.read_bytes(), "s.zip"), work, MB)
    assert saved.file_type == FileType.SHAPEFILE


def test_empty_file_rejected_and_cleaned(work):
    with pytest.raises(InvalidRequest):
        save_upload(upload_file(b"", "a.kml"), work, MB)
    assert list(work.iterdir()) == []


def test_over_size_rejected_and_partial_file_removed(work):
    with pytest.raises(FileTooLarge):
        save_upload(upload_file(b"<" + b"x" * (2 * MB), "a.kml"), work, MB)
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("name", ["a.geojson", "a.kmz", "a.shp", "a", "a.txt"])
def test_unsupported_extension(work, name):
    with pytest.raises(UnsupportedFileType):
        save_upload(upload_file(b"<kml/>", name), work, MB)


def test_kmz_message_has_hint(work):
    with pytest.raises(UnsupportedFileType, match="KMZ"):
        save_upload(upload_file(b"PK", "a.kmz"), work, MB)


def test_zip_extension_but_not_a_zip(work):
    with pytest.raises(UnsupportedFileType):
        save_upload(upload_file(b"this is not a zip", "a.zip"), work, MB)
    assert list(work.iterdir()) == []


def test_kml_extension_but_not_xml(work):
    with pytest.raises(UnsupportedFileType):
        save_upload(upload_file(b"PK\x03\x04binary", "a.kml"), work, MB)


def test_client_filename_with_path_parts_is_reduced_to_base_name(work):
    saved = save_upload(upload_file(_kml_bytes(), "../../etc/evil.kml"), work, MB)
    assert saved.filename == "evil.kml"
    assert saved.path.parent == work
    assert clean_filename("C:\\Users\\x\\plot.kml") == "plot.kml"
    assert clean_filename(None) == "upload"
    assert clean_filename("a\x00b.kml") == "ab.kml"


# --- zip extraction ---------------------------------------------------------


def _extract(zip_path, dest, **kw):
    return extract_shapefile_zip(
        zip_path,
        dest,
        max_uncompressed_bytes=kw.get("max_bytes", 50 * MB),
        max_entries=kw.get("max_entries", 20),
    )


def test_extract_valid_zip(work, tmp_path):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "s.zip")
    shp = _extract(z, work)
    assert shp.name == "data.shp" and shp.exists()
    assert (work / "data.prj").exists() and (work / "data.dbf").exists()


def test_extract_nested_folder(work, tmp_path):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "s.zip", nested_folder=True)
    assert _extract(z, work).exists()


def test_missing_prj_rejected_with_clear_message(work, tmp_path):
    z = write_shapefile_zip(make_gdf([square(77.5, 12.9)]), tmp_path / "s.zip", include_prj=False)
    with pytest.raises(UnprocessableFile, match=r"no \.prj"):
        _extract(z, work)


def test_missing_dbf_rejected(work, tmp_path):
    z = write_shapefile_zip(
        make_gdf([square(77.5, 12.9)]), tmp_path / "s.zip", drop_parts=(".dbf",)
    )
    with pytest.raises(UnprocessableFile, match=r"\.dbf"):
        _extract(z, work)


def test_no_shp_rejected(work, tmp_path):
    z = make_zip(tmp_path / "z.zip", {"readme.txt": b"hello"})
    with pytest.raises(UnprocessableFile, match=r"\.shp"):
        _extract(z, work)


def test_two_shp_rejected(work, tmp_path):
    z = make_zip(tmp_path / "z.zip", {"a.shp": b"x", "b.shp": b"y"})
    with pytest.raises(UnprocessableFile, match="more than one"):
        _extract(z, work)


@pytest.mark.parametrize(
    "name", ["../evil.txt", "a/../../evil.txt", "/abs/evil.txt", "C:/evil.txt", "..\\evil.txt"]
)
def test_zip_slip_rejected_and_nothing_written(work, tmp_path, name):
    z = make_zip(tmp_path / "z.zip", {name: b"x", "data.shp": b"x"})
    with pytest.raises(UnprocessableFile, match="unsafe"):
        _extract(z, work)
    assert list(work.iterdir()) == []
    assert not (tmp_path / "evil.txt").exists()


def test_too_many_entries_rejected(work, tmp_path):
    z = make_zip(tmp_path / "z.zip", {f"f{i}.txt": b"x" for i in range(30)})
    with pytest.raises(UnprocessableFile, match="too many"):
        _extract(z, work, max_entries=20)


def test_zip_bomb_by_declared_size_rejected(work, tmp_path):
    z = make_zip(tmp_path / "z.zip", {"data.shp": b"0" * (3 * MB)})
    assert z.stat().st_size < 100_000  # compresses to almost nothing
    with pytest.raises(UnprocessableFile, match="too large"):
        _extract(z, work, max_bytes=1 * MB)


def test_corrupt_zip_rejected(work, tmp_path):
    z = tmp_path / "bad.zip"
    z.write_bytes(b"PK\x03\x04" + b"garbage" * 10)
    with pytest.raises(UnprocessableFile):
        _extract(z, work)
