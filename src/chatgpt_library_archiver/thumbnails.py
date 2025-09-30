"""Helpers for creating and maintaining gallery thumbnails."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .status import StatusReporter

THUMBNAIL_DIR_NAME = "thumbs"
THUMBNAIL_SIZE: tuple[int, int] = (512, 512)

_RESAMPLING = getattr(Image, "Resampling", Image)
_LANCZOS = getattr(_RESAMPLING, "LANCZOS", Image.BICUBIC)

_EXT_TO_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".gif": "GIF",
    ".bmp": "BMP",
    ".tiff": "TIFF",
    ".tif": "TIFF",
}


def thumbnail_relative_path(filename: str) -> str:
    """Return the metadata value for a thumbnail path."""

    return f"{THUMBNAIL_DIR_NAME}/{filename}"


def _infer_format(dest: Path, image: Image.Image) -> str:
    ext = dest.suffix.lower()
    if ext in _EXT_TO_FORMAT:
        return _EXT_TO_FORMAT[ext]
    if image.format:
        return image.format
    return "PNG"


def create_thumbnail(
    source: Path, dest: Path, *, reporter: StatusReporter | None = None
) -> None:
    """Create a thumbnail for ``source`` at ``dest``."""

    if reporter is not None:
        reporter.log_status("Generating thumbnail for", source.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail(THUMBNAIL_SIZE, _LANCZOS)
            fmt = _infer_format(dest, img)
            save_kwargs = {}
            if fmt == "JPEG":
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                save_kwargs["quality"] = 85
                save_kwargs["optimize"] = True
            elif fmt == "PNG":
                if img.mode == "P":
                    img = img.convert("RGBA")
                save_kwargs["optimize"] = True
            img.save(dest, fmt, **save_kwargs)
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Failed to create thumbnail for {source}: {exc}") from exc


def regenerate_thumbnails(
    gallery_root: Path,
    metadata: Iterable[dict],
    *,
    force: bool = False,
    reporter: StatusReporter | None = None,
) -> tuple[list[str], bool]:
    """Ensure thumbnails exist for each metadata entry.

    Returns a tuple of ``(processed_filenames, metadata_updated)``.
    """

    processed: list[str] = []
    updated = False
    images_dir = gallery_root / "images"

    entries = list(metadata)
    pending: list[tuple[str, Path, Path]] = []

    for entry in entries:
        filename = entry.get("filename")
        if not filename:
            continue
        source = images_dir / filename
        if not source.is_file():
            continue
        processed.append(filename)
        thumb_rel = thumbnail_relative_path(filename)
        thumb_path = gallery_root / thumb_rel
        need_create = force or not thumb_path.exists()
        if need_create:
            pending.append((filename, source, thumb_path))
        if entry.get("thumbnail") != thumb_rel:
            entry["thumbnail"] = thumb_rel
            updated = True

    if reporter is not None and pending:
        reporter.add_total(len(pending))

    for _filename, source, thumb_path in pending:
        create_thumbnail(source, thumb_path, reporter=reporter)
        if reporter is not None:
            reporter.advance()

    return processed, updated
