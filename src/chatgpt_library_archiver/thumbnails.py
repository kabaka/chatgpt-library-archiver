"""Helpers for creating and maintaining gallery thumbnails."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .status import StatusReporter

THUMBNAIL_DIR_NAME = "thumbs"
THUMBNAIL_SIZES: dict[str, tuple[int, int]] = {
    "small": (150, 150),
    "medium": (250, 250),
    "large": (400, 400),
}

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


def thumbnail_relative_path(filename: str, size: str = "medium") -> str:
    """Return the metadata value for a thumbnail path.

    Parameters
    ----------
    filename:
        The image filename the thumbnail corresponds to.
    size:
        The gallery size bucket (``small``, ``medium``, ``large``).
    """

    if size not in THUMBNAIL_SIZES:
        raise ValueError(f"Unsupported thumbnail size: {size}")
    return f"{THUMBNAIL_DIR_NAME}/{size}/{filename}"


def thumbnail_relative_paths(filename: str) -> dict[str, str]:
    """Return relative thumbnail paths for every configured size."""

    return {size: thumbnail_relative_path(filename, size) for size in THUMBNAIL_SIZES}


def _infer_format(dest: Path, image: Image.Image) -> str:
    ext = dest.suffix.lower()
    if ext in _EXT_TO_FORMAT:
        return _EXT_TO_FORMAT[ext]
    if image.format:
        return image.format
    return "PNG"


def _prepare_for_format(img: Image.Image, fmt: str) -> tuple[Image.Image, dict[str, object]]:
    """Return an image and keyword arguments tuned for the target format."""

    save_kwargs: dict[str, object] = {}
    fmt = fmt.upper()
    if fmt == "JPEG":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        save_kwargs.update({
            "quality": 80,
            "optimize": True,
            "progressive": True,
            "subsampling": 2,
        })
    elif fmt == "PNG":
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        save_kwargs.update({
            "optimize": True,
            "compress_level": 9,
        })
    elif fmt == "WEBP":
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        save_kwargs.update({
            "quality": 80,
            "method": 6,
        })
    elif fmt == "GIF":
        if img.mode not in ("P", "L"):
            img = img.convert("P", palette=Image.ADAPTIVE)
        save_kwargs["optimize"] = True
    return img, save_kwargs


def create_thumbnails(
    source: Path, dest_map: dict[str, Path], *, reporter: StatusReporter | None = None
) -> None:
    """Create thumbnails for ``source`` at every ``dest`` path provided."""

    if reporter is not None:
        reporter.log_status("Generating thumbnails for", source.name)
    try:
        with Image.open(source) as img:
            base = ImageOps.exif_transpose(img)
            for size, dest in dest_map.items():
                if size not in THUMBNAIL_SIZES:
                    raise ValueError(f"Unsupported thumbnail size: {size}")
                target_size = THUMBNAIL_SIZES[size]
                thumb = base.copy()
                thumb.thumbnail(target_size, _LANCZOS)
                dest.parent.mkdir(parents=True, exist_ok=True)
                fmt = _infer_format(dest, thumb)
                prepared, save_kwargs = _prepare_for_format(thumb, fmt)
                prepared.save(dest, fmt, **save_kwargs)
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
    pending: list[tuple[str, Path, dict[str, Path]]] = []

    for entry in entries:
        filename = entry.get("filename")
        if not filename:
            continue
        source = images_dir / filename
        if not source.is_file():
            continue
        processed.append(filename)
        thumb_rel_map = thumbnail_relative_paths(filename)
        thumb_path_map = {size: gallery_root / rel for size, rel in thumb_rel_map.items()}
        need_create = force or any(not path.exists() for path in thumb_path_map.values())
        if need_create:
            pending.append((filename, source, thumb_path_map))
        if entry.get("thumbnails") != thumb_rel_map:
            entry["thumbnails"] = thumb_rel_map
            updated = True
        medium_rel = thumb_rel_map["medium"]
        if entry.get("thumbnail") != medium_rel:
            entry["thumbnail"] = medium_rel
            updated = True

    if reporter is not None and pending:
        reporter.add_total(len(pending))

    for _filename, source, thumb_paths in pending:
        create_thumbnails(source, thumb_paths, reporter=reporter)
        if reporter is not None:
            reporter.advance()

    return processed, updated
