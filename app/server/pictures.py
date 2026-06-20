"""Picture-folder service layer for the web config.

Pure, testable functions backing the ``/api/pictures*`` routes: list, save an
upload, rename, delete, and produce thumbnails for the local artwork folder
(the directory used by artwork *folder* mode).

The security core is :func:`safe_picture_path`: every operation that names a
file resolves through it, guaranteeing the result sits **directly inside** the
configured folder (no ``..``, no separators, no absolute paths, no symlink
escape). Uploads are additionally validated as real images.

These functions never write the config YAML and never trigger a reload: the
renderer rescans the folder on every render, so picture changes take effect on
the next artwork frame.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from app.renderer.components.artwork import _FOLDER_IMAGE_EXTS, list_folder_images

logger = logging.getLogger(__name__)

# Hard cap on upload size, enforced server-side (do not trust Content-Length).
_DEFAULT_MAX_BYTES: int = 25 * 1024 * 1024


class PictureError(ValueError):
    """Raised for invalid picture names / unsupported content."""


def safe_picture_path(folder: Path, name: str) -> Path:
    """Resolve *name* to a path guaranteed to sit directly inside *folder*.

    Rejects: empty names, names containing path separators or '..', absolute
    paths, dotfiles, and any resolved path that escapes *folder* (symlink or
    otherwise). Raises :class:`PictureError` on any violation.
    """
    raw = (name or "").strip()
    if not raw or raw.startswith(".") or "/" in raw or "\\" in raw or raw in ("..", "."):
        raise PictureError(f"Nome file non valido: {name!r}")
    candidate = (folder / raw).resolve()
    # Containment via parent equality, not str.startswith (which is fooled by
    # sibling dirs like 'pictures-evil').
    if candidate.parent != folder.resolve():
        raise PictureError("Percorso fuori dalla cartella consentita.")
    return candidate


def list_pictures(folder: Path) -> list[dict]:
    """Return ``[{name, size_bytes, modified_iso}]`` sorted case-insensitively.

    Each entry maps to a UI list row; ``size_bytes``/``modified_iso`` are
    display-only niceties. A missing folder yields an empty list.
    """
    rows: list[dict] = []
    for path in list_folder_images(folder):
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_iso": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return rows


def _unique_name(folder: Path, name: str) -> str:
    """Return *name*, or a ``stem-1.ext``/``stem-2.ext`` variant if it exists."""
    candidate = folder / name
    if not candidate.exists():
        return name
    stem = candidate.stem
    suffix = candidate.suffix
    i = 1
    while True:
        alt = f"{stem}-{i}{suffix}"
        if not (folder / alt).exists():
            return alt
        i += 1


def save_upload(
    folder: Path,
    filename: str,
    data: bytes,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> str:
    """Validate and write an uploaded image; return the stored file name.

    - sanitise the client filename through :func:`safe_picture_path`;
    - reject extensions not in ``_FOLDER_IMAGE_EXTS``;
    - reject data larger than *max_bytes*;
    - verify the bytes are a real image (``Image.open(...).verify()``);
    - on name collision, suffix ``-1``, ``-2``, … rather than overwriting.

    Writes atomically (temp file in the same dir + ``os.replace``) so a crash
    mid-write can't leave a truncated image the renderer would fail to open.
    """
    # Validate the requested name and extension first (cheap, before reading).
    requested = safe_picture_path(folder, filename)
    if requested.suffix.lower() not in _FOLDER_IMAGE_EXTS:
        raise PictureError(
            f"Estensione non supportata: {requested.suffix or '(nessuna)'}"
        )
    if len(data) > max_bytes:
        raise PictureError(
            f"File troppo grande ({len(data)} byte, massimo {max_bytes})."
        )
    if not data:
        raise PictureError("File vuoto.")

    # Verify the bytes are a real image. verify() invalidates the object, so we
    # only use it to validate; the original bytes are written verbatim below.
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:  # noqa: BLE001
        raise PictureError("Il file non è un'immagine valida.") from exc

    folder.mkdir(parents=True, exist_ok=True)
    final_name = _unique_name(folder, requested.name)
    final_path = folder / final_name
    tmp_path = folder / f".{final_name}.tmp"
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, final_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    logger.info("save_upload: salvata %s (%d byte)", final_name, len(data))
    return final_name


def rename_picture(folder: Path, old: str, new: str) -> str:
    """Rename within *folder*; return the final name.

    Both names pass :func:`safe_picture_path`. If *new* has no extension, the old
    one is preserved. The resulting extension must stay in ``_FOLDER_IMAGE_EXTS``.
    Refuses to clobber an existing file.
    """
    old_path = safe_picture_path(folder, old)
    if not old_path.is_file():
        raise PictureError(f"File inesistente: {old!r}")

    new_raw = (new or "").strip()
    # Preserve the original extension when the new name has none.
    if not Path(new_raw).suffix:
        new_raw = new_raw + old_path.suffix

    new_path = safe_picture_path(folder, new_raw)
    if new_path.suffix.lower() not in _FOLDER_IMAGE_EXTS:
        raise PictureError(
            f"Estensione non supportata: {new_path.suffix or '(nessuna)'}"
        )
    if new_path == old_path:
        return old_path.name
    if new_path.exists():
        raise PictureError(f"Esiste già un file con questo nome: {new_path.name!r}")

    os.replace(old_path, new_path)
    logger.info("rename_picture: %s -> %s", old_path.name, new_path.name)
    return new_path.name


def delete_picture(folder: Path, name: str) -> None:
    """Delete a single file resolved via :func:`safe_picture_path`.

    A missing file raises :class:`PictureError`.
    """
    path = safe_picture_path(folder, name)
    if not path.is_file():
        raise PictureError(f"File inesistente: {name!r}")
    path.unlink()
    logger.info("delete_picture: eliminata %s", path.name)


def thumbnail_bytes(path: Path, max_side: int = 320) -> bytes:
    """Return JPEG bytes of a downscaled copy of the image at *path*.

    Applies ``ImageOps.exif_transpose`` so portrait photos are oriented
    correctly, then ``thumbnail`` (preserving aspect ratio). Used for list rows
    and previews so the browser never loads the full multi-megabyte file.
    """
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
    return buf.getvalue()
