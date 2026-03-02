"""Helpers for creating and maintaining gallery thumbnails."""

from __future__ import annotations

import concurrent.futures
import io
import multiprocessing
import os
import threading
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing.context import BaseContext
from multiprocessing.managers import SyncManager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from PIL import Image, ImageOps, UnidentifiedImageError

from .status import StatusReporter


class ThumbnailError(RuntimeError):
    """An image failed thumbnail generation."""


# Guard against decompression bombs.  Pillow's default (~178 MP) is close
# enough to be a risk when multiple ProcessPoolExecutor workers each open a
# large image simultaneously.  200 MP is generous for any real photograph
# while still rejecting pathological payloads.  See also the security audit
# finding M-4 and the image-pipeline review §4.
Image.MAX_IMAGE_PIXELS = 200_000_000

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .metadata import GalleryItem


def _entry_get(entry: GalleryItem, key: str) -> Any:
    return getattr(entry, key, None)


def _entry_set(entry: GalleryItem, key: str, value: Any) -> None:
    setattr(entry, key, value)


class _StatusQueueProtocol(Protocol):
    """Minimal protocol for status queue objects used by workers."""

    def put(
        self, item: object, block: bool = True, timeout: float | None = None
    ) -> None:
        """Send ``item`` to the queue."""

    def get(self) -> object:
        """Retrieve a message from the queue."""


THUMBNAIL_DIR_NAME = "thumbs"
THUMBNAIL_SIZES: dict[str, tuple[int, int]] = {
    "small": (150, 150),
    "medium": (250, 250),
    "large": (400, 400),
}

_LANCZOS: Image.Resampling = Image.Resampling.LANCZOS

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


def thumbnail_relative_path(
    filename: str, size: str = "medium", *, webp: bool = False
) -> str:
    """Return the metadata value for a thumbnail path.

    Parameters
    ----------
    filename:
        The image filename the thumbnail corresponds to.
    size:
        The gallery size bucket (``small``, ``medium``, ``large``).
    webp:
        When ``True``, replace the file extension with ``.webp``.
    """

    if size not in THUMBNAIL_SIZES:
        raise ValueError(f"Unsupported thumbnail size: {size}")
    if webp:
        stem = Path(filename).stem
        filename = f"{stem}.webp"
    return f"{THUMBNAIL_DIR_NAME}/{size}/{filename}"


def thumbnail_relative_paths(filename: str, *, webp: bool = False) -> dict[str, str]:
    """Return relative thumbnail paths for every configured size."""

    return {
        size: thumbnail_relative_path(filename, size, webp=webp)
        for size in THUMBNAIL_SIZES
    }


def _infer_format(dest: Path, image: Image.Image) -> str:
    ext = dest.suffix.lower()
    if ext in _EXT_TO_FORMAT:
        return _EXT_TO_FORMAT[ext]
    if image.format:
        return image.format
    return "PNG"


def _prepare_for_format(
    img: Image.Image, fmt: str
) -> tuple[Image.Image, dict[str, object]]:
    """Return an image and keyword arguments tuned for the target format."""

    save_kwargs: dict[str, object] = {}
    fmt = fmt.upper()
    if fmt == "JPEG":
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        save_kwargs.update(
            {
                "quality": 80,
                "optimize": True,
                "progressive": True,
                "subsampling": 2,
            }
        )
    elif fmt == "PNG":
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        save_kwargs.update(
            {
                "optimize": True,
                "compress_level": 9,
            }
        )
    elif fmt == "WEBP":
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")
        save_kwargs.update(
            {
                "quality": 80,
                "method": 6,
            }
        )
    elif fmt == "GIF":
        if img.mode not in ("P", "L"):
            img = img.convert("P", palette=Image.Palette.ADAPTIVE)
        save_kwargs["optimize"] = True
    return img, save_kwargs


def _ensure_srgb(img: Image.Image) -> Image.Image:
    """Convert *img* to sRGB and strip the ICC profile for consistent rendering.

    If the image has an embedded ICC profile that is NOT sRGB the image is
    colour-managed into sRGB via ``ImageCms``.  If the profile is already
    sRGB (description contains ``"srgb"``) the profile is simply removed.
    On any failure the profile is stripped and the image is returned
    unmodified so a single corrupt profile never blocks the pipeline.
    """

    icc_data = img.info.get("icc_profile")
    if not icc_data:
        return img

    try:
        from PIL import ImageCms

        src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_data))

        # Fast path: if the profile is already sRGB, just strip it.
        try:
            desc = ImageCms.getProfileDescription(src_profile).strip().lower()
            if "srgb" in desc:
                img.info.pop("icc_profile", None)
                return img
        except Exception:
            pass

        srgb_profile: object = ImageCms.createProfile("sRGB")  # type: ignore[reportUnknownVariableType, reportUnknownMemberType]

        if img.mode == "RGB":
            converted = ImageCms.profileToProfile(
                img,
                src_profile,
                srgb_profile,  # type: ignore[arg-type]
                renderingIntent=ImageCms.Intent.PERCEPTUAL,
                outputMode="RGB",
            )
            if converted is not None:
                img = converted
        elif img.mode == "RGBA":
            # ImageCms doesn't handle RGBA directly; split, convert, reattach.
            alpha = img.split()[3]
            rgb = img.convert("RGB")
            rgb.info["icc_profile"] = icc_data
            rgb_converted = ImageCms.profileToProfile(
                rgb,
                src_profile,
                srgb_profile,  # type: ignore[arg-type]
                renderingIntent=ImageCms.Intent.PERCEPTUAL,
                outputMode="RGB",
            )
            if rgb_converted is not None:
                rgb_converted.putalpha(alpha)
                img = rgb_converted
        # For other modes (L, P, etc.) just strip the profile below.

        img.info.pop("icc_profile", None)
    except Exception:
        # Corrupt profile, missing ImageCms, etc. — strip and continue.
        img.info.pop("icc_profile", None)

    return img


def create_thumbnails(
    source: Path,
    dest_map: dict[str, Path],
    *,
    reporter: StatusReporter | None = None,
    webp: bool = False,
) -> None:
    """Create thumbnails for ``source`` at every ``dest`` path provided.

    When *webp* is ``True`` every thumbnail is saved in WebP format
    regardless of the source format.  The destination paths are
    rewritten to use a ``.webp`` extension.
    """

    if reporter is not None:
        reporter.log_status("Generating thumbnails for", source.name)
    try:
        with Image.open(source) as img:
            base = ImageOps.exif_transpose(img)
            base = _ensure_srgb(base)
            for size, dest in dest_map.items():
                if size not in THUMBNAIL_SIZES:
                    raise ValueError(f"Unsupported thumbnail size: {size}")
                target_size = THUMBNAIL_SIZES[size]
                thumb = base.copy()
                thumb.thumbnail(target_size, _LANCZOS)
                if webp:
                    dest = dest.with_suffix(".webp")
                    fmt = "WEBP"
                else:
                    fmt = _infer_format(dest, thumb)
                dest.parent.mkdir(parents=True, exist_ok=True)
                prepared, save_kwargs = _prepare_for_format(thumb, fmt)
                prepared.save(dest, fmt, **save_kwargs)
                if prepared is not thumb:
                    prepared.close()
                thumb.close()
        if reporter is not None:
            reporter.log_status("Finished generating thumbnails for", source.name)
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise ThumbnailError(f"Failed to create thumbnail for {source}: {exc}") from exc


def _create_thumbnails_worker(
    source: Path,
    dest_map: dict[str, Path],
    status_queue: _StatusQueueProtocol | None = None,
    webp: bool = False,
) -> str:
    """Create thumbnails for ``source`` without side-channel reporting."""

    if status_queue is not None:
        status_queue.put(("start", source.name))
    try:
        create_thumbnails(source, dest_map, reporter=None, webp=webp)
    except Exception as exc:
        if status_queue is not None:
            status_queue.put(("error", source.name, str(exc)))
        raise
    else:
        if status_queue is not None:
            status_queue.put(("finish", source.name))
    return source.name


def _consume_status_messages(
    status_queue: _StatusQueueProtocol,
    reporter: StatusReporter,
) -> None:
    """Forward worker status updates to ``reporter``."""

    while True:
        raw = status_queue.get()
        if raw is None:
            break
        message = cast(tuple[str, ...], raw)
        kind = message[0]
        name = message[1]
        rest = message[2:]
        if kind == "start":
            reporter.log_status("Generating thumbnails for", name)
        elif kind == "finish":
            reporter.log_status("Finished generating thumbnails for", name)
        elif kind == "error":
            detail = rest[0] if rest else ""
            suffix = f": {detail}" if detail else ""
            reporter.log_status("Failed to generate thumbnails for", f"{name}{suffix}")


def ensure_thumbnail_metadata(
    gallery_root: Path,
    metadata: Iterable[GalleryItem],
    *,
    webp: bool = False,
) -> bool:
    """Update metadata thumbnail paths without generating images.

    Iterates over *metadata* entries and ensures each item's ``thumbnails``
    and ``thumbnail`` fields contain the correct relative paths.  No file
    existence checks or image I/O are performed.

    When *webp* is ``True`` the thumbnail paths use ``.webp`` extensions.

    Returns ``True`` if any metadata entry was changed.
    """

    updated = False
    for entry in metadata:
        filename = _entry_get(entry, "filename")
        if not filename:
            continue
        thumb_rel_map = thumbnail_relative_paths(filename, webp=webp)
        if _entry_get(entry, "thumbnails") != thumb_rel_map:
            _entry_set(entry, "thumbnails", thumb_rel_map)
            updated = True
        medium_rel = thumb_rel_map["medium"]
        if _entry_get(entry, "thumbnail") != medium_rel:
            _entry_set(entry, "thumbnail", medium_rel)
            updated = True
    return updated


def regenerate_thumbnails(
    gallery_root: Path,
    metadata: Iterable[GalleryItem],
    *,
    force: bool = False,
    reporter: StatusReporter | None = None,
    max_workers: int | None = None,
    webp: bool = False,
) -> tuple[list[str], bool]:
    """Ensure thumbnails exist for each metadata entry.

    Returns a tuple of ``(processed_filenames, metadata_updated)``.
    """

    processed: list[str] = []
    images_dir = gallery_root / "images"

    if max_workers is not None and max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    entries = list(metadata)
    pending: list[tuple[str, Path, dict[str, Path]]] = []

    for entry in entries:
        filename = _entry_get(entry, "filename")
        if not filename:
            continue
        source = images_dir / filename
        if not source.is_file():
            continue
        processed.append(filename)
        thumb_rel_map = thumbnail_relative_paths(filename, webp=webp)
        thumb_path_map = {
            size: gallery_root / rel for size, rel in thumb_rel_map.items()
        }
        need_create = force or any(
            not path.exists() for path in thumb_path_map.values()
        )
        if not need_create:
            source_mtime = source.stat().st_mtime
            need_create = any(
                path.stat().st_mtime < source_mtime
                for path in thumb_path_map.values()
                if path.exists()
            )
        if need_create:
            pending.append((filename, source, thumb_path_map))

    # Delegate metadata fixup to the lightweight helper.
    updated = ensure_thumbnail_metadata(gallery_root, entries, webp=webp)

    if reporter is not None and pending:
        reporter.add_total(len(pending))

    if not pending:
        return processed, updated

    if max_workers == 1 or len(pending) == 1:
        for _filename, source, thumb_paths in pending:
            try:
                create_thumbnails(source, thumb_paths, reporter=reporter, webp=webp)
            except Exception as exc:
                if reporter is not None:
                    reporter.report_error(
                        "Thumbnail generation failed",
                        _filename,
                        reason=str(exc),
                        exception=exc,
                    )
            if reporter is not None:
                reporter.advance()
        return processed, updated

    executor_kwargs: dict[str, object] = {}
    if max_workers is None:
        max_workers = min(os.cpu_count() or 1, 8)
    executor_kwargs["max_workers"] = max_workers

    status_queue: _StatusQueueProtocol | None = None
    status_thread: threading.Thread | None = None
    status_manager: SyncManager | None = None
    mp_context: BaseContext | None = None
    if reporter is not None:
        mp_context = multiprocessing.get_context()
        status_manager = mp_context.Manager()
        status_queue = status_manager.Queue()
        status_thread = threading.Thread(
            target=_consume_status_messages,
            args=(status_queue, reporter),
            daemon=True,
        )
        status_thread.start()

    try:
        with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_context,
        ) as executor:
            pending_iter = iter(pending)
            futures: set[concurrent.futures.Future[str]] = set()
            future_filenames: dict[concurrent.futures.Future[str], str] = {}

            def submit_next() -> bool:
                try:
                    _filename, source, thumb_paths = next(pending_iter)
                except StopIteration:
                    return False
                future = executor.submit(
                    _create_thumbnails_worker,
                    source,
                    thumb_paths,
                    status_queue,
                    webp,
                )
                futures.add(future)
                future_filenames[future] = _filename
                return True

            worker_limit = getattr(executor, "_max_workers", None)
            if worker_limit is None:
                worker_limit = len(pending)
            for _ in range(worker_limit):
                if not submit_next():
                    break

            while futures:
                future = next(as_completed(futures))
                futures.remove(future)
                fname = future_filenames.pop(future, "unknown")
                try:
                    future.result()
                except Exception as exc:
                    if reporter is not None:
                        reporter.report_error(
                            "Thumbnail generation failed",
                            fname,
                            reason=str(exc),
                            exception=exc,
                        )
                if reporter is not None:
                    reporter.advance()
                submit_next()
    finally:
        if status_queue is not None and status_thread is not None:
            try:
                status_queue.put(None)
            finally:
                status_thread.join()
        if status_manager is not None:
            status_manager.shutdown()

    return processed, updated
