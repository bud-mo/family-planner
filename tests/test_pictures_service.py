"""Unit tests for the picture-folder service layer (app/server/pictures.py).

These exercise the security-critical path containment plus the upload/rename/
delete/thumbnail behaviour with no FastAPI involved.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.renderer.components.artwork import resolve_artwork_folder
from app.server.pictures import (
    PictureError,
    delete_picture,
    list_pictures,
    rename_picture,
    safe_picture_path,
    save_upload,
    thumbnail_bytes,
)


def _jpeg_bytes(size: tuple[int, int] = (32, 24), color: str = "red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


# --------------------------------------------------------------------------
# safe_picture_path
# --------------------------------------------------------------------------


def test_safe_picture_path_accepts_plain_name(tmp_path: Path):
    result = safe_picture_path(tmp_path, "cat.jpg")
    assert result == (tmp_path / "cat.jpg").resolve()
    assert result.parent == tmp_path.resolve()


@pytest.mark.parametrize(
    "bad",
    ["..", ".", "../x", "/abs/path", "a/b", "a\\b", ".hidden", "", "   "],
)
def test_safe_picture_path_rejects_unsafe(tmp_path: Path, bad: str):
    with pytest.raises(PictureError):
        safe_picture_path(tmp_path, bad)


def test_safe_picture_path_rejects_symlink_escape(tmp_path: Path):
    folder = tmp_path / "pics"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"x")
    # A symlink inside the folder pointing outside must not be accepted as a
    # containment target.
    link = folder / "link.jpg"
    try:
        link.symlink_to(outside / "secret.jpg")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(PictureError):
        safe_picture_path(folder, "link.jpg")


# --------------------------------------------------------------------------
# list_pictures
# --------------------------------------------------------------------------


def test_list_pictures_sorted_with_metadata(tmp_path: Path):
    (tmp_path / "b.jpg").write_bytes(_jpeg_bytes())
    (tmp_path / "A.png").write_bytes(_jpeg_bytes())
    (tmp_path / "notes.txt").write_text("ignore me")
    rows = list_pictures(tmp_path)
    assert [r["name"] for r in rows] == ["A.png", "b.jpg"]
    assert all("size_bytes" in r and "modified_iso" in r for r in rows)


def test_list_pictures_missing_folder(tmp_path: Path):
    assert list_pictures(tmp_path / "nope") == []


# --------------------------------------------------------------------------
# save_upload
# --------------------------------------------------------------------------


def test_save_upload_writes_valid_jpeg(tmp_path: Path):
    name = save_upload(tmp_path, "photo.jpg", _jpeg_bytes())
    assert name == "photo.jpg"
    assert (tmp_path / "photo.jpg").is_file()


def test_save_upload_rejects_bad_extension(tmp_path: Path):
    with pytest.raises(PictureError):
        save_upload(tmp_path, "note.txt", _jpeg_bytes())


def test_save_upload_rejects_non_image(tmp_path: Path):
    with pytest.raises(PictureError):
        save_upload(tmp_path, "fake.jpg", b"this is not an image")


def test_save_upload_rejects_oversize(tmp_path: Path):
    with pytest.raises(PictureError):
        save_upload(tmp_path, "big.jpg", _jpeg_bytes(), max_bytes=10)


def test_save_upload_collision_suffix(tmp_path: Path):
    save_upload(tmp_path, "pic.jpg", _jpeg_bytes())
    second = save_upload(tmp_path, "pic.jpg", _jpeg_bytes())
    assert second == "pic-1.jpg"
    assert (tmp_path / "pic-1.jpg").is_file()


def test_save_upload_rejects_traversal_name(tmp_path: Path):
    with pytest.raises(PictureError):
        save_upload(tmp_path, "../evil.jpg", _jpeg_bytes())


# --------------------------------------------------------------------------
# rename_picture
# --------------------------------------------------------------------------


def test_rename_picture_basic(tmp_path: Path):
    save_upload(tmp_path, "old.jpg", _jpeg_bytes())
    final = rename_picture(tmp_path, "old.jpg", "new.jpg")
    assert final == "new.jpg"
    assert not (tmp_path / "old.jpg").exists()
    assert (tmp_path / "new.jpg").is_file()


def test_rename_picture_preserves_extension_when_missing(tmp_path: Path):
    save_upload(tmp_path, "old.jpg", _jpeg_bytes())
    final = rename_picture(tmp_path, "old.jpg", "renamed")
    assert final == "renamed.jpg"


def test_rename_picture_refuses_clobber(tmp_path: Path):
    save_upload(tmp_path, "a.jpg", _jpeg_bytes())
    save_upload(tmp_path, "b.jpg", _jpeg_bytes())
    with pytest.raises(PictureError):
        rename_picture(tmp_path, "a.jpg", "b.jpg")


def test_rename_picture_rejects_unsafe_new(tmp_path: Path):
    save_upload(tmp_path, "a.jpg", _jpeg_bytes())
    with pytest.raises(PictureError):
        rename_picture(tmp_path, "a.jpg", "../escape.jpg")


def test_rename_picture_missing_source(tmp_path: Path):
    with pytest.raises(PictureError):
        rename_picture(tmp_path, "ghost.jpg", "new.jpg")


# --------------------------------------------------------------------------
# delete_picture
# --------------------------------------------------------------------------


def test_delete_picture(tmp_path: Path):
    save_upload(tmp_path, "x.jpg", _jpeg_bytes())
    delete_picture(tmp_path, "x.jpg")
    assert not (tmp_path / "x.jpg").exists()


def test_delete_picture_missing(tmp_path: Path):
    with pytest.raises(PictureError):
        delete_picture(tmp_path, "ghost.jpg")


# --------------------------------------------------------------------------
# thumbnail_bytes
# --------------------------------------------------------------------------


def test_thumbnail_bytes_downscales(tmp_path: Path):
    src = tmp_path / "big.jpg"
    Image.new("RGB", (2000, 1500), "blue").save(src, format="JPEG")
    data = thumbnail_bytes(src, max_side=100)
    with Image.open(io.BytesIO(data)) as thumb:
        assert max(thumb.size) <= 100
        assert thumb.format == "JPEG"


# --------------------------------------------------------------------------
# resolve_artwork_folder (parents[3] index assertion)
# --------------------------------------------------------------------------


def test_resolve_artwork_folder_relative_to_project_root():
    resolved = resolve_artwork_folder("pictures")
    # Project root contains pyproject/README and the app package.
    assert resolved.name == "pictures"
    assert (resolved.parent / "app").is_dir()


def test_resolve_artwork_folder_absolute_passthrough(tmp_path: Path):
    assert resolve_artwork_folder(tmp_path) == tmp_path.resolve()
