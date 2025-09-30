"""Helpers for creating and maintaining gallery thumbnails."""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import threading
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing.context import BaseContext
from multiprocessing.managers import SyncManager
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from .status import StatusReporter


class _StatusQueueProtocol(Protocol):
    """Minimal protocol for status queue objects used by workers."""

    def put(
        self, message: object, block: bool = True, timeout: float | None = None
    ) -> None:  # noqa: D401
        """Send ``message`` to the queue."""

    def get(self) -> object:  # noqa: D401
        """Retrieve a message from the queue."""


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


def _prepare_for_format(
    img: Image.Image, fmt: str
) -> tuple[Image.Image, dict[str, object]]:
    """Return an image and keyword arguments tuned for the target format."""

    save_kwargs: dict[str, object] = {}
    fmt = fmt.upper()
    if fmt == "JPEG":
        if img.mode not in ("RGB", "L"):
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
        if reporter is not None:
            reporter.log_status("Finished generating thumbnails for", source.name)
    except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Failed to create thumbnail for {source}: {exc}") from exc


def _create_thumbnails_worker(
    source: Path,
    dest_map: dict[str, Path],
    status_queue: _StatusQueueProtocol | None = None,
) -> str:
    """Create thumbnails for ``source`` without side-channel reporting."""

    if status_queue is not None:
        status_queue.put(("start", source.name))
    try:
        create_thumbnails(source, dest_map, reporter=None)
    except Exception as exc:  # noqa: BLE001
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
        message = status_queue.get()
        if message is None:
            break
        kind, name, *rest = message
        if kind == "start":
            reporter.log_status("Generating thumbnails for", name)
        elif kind == "finish":
            reporter.log_status("Finished generating thumbnails for", name)
        elif kind == "error":
            detail = rest[0] if rest else ""
            suffix = f": {detail}" if detail else ""
            reporter.log_status("Failed to generate thumbnails for", f"{name}{suffix}")


def regenerate_thumbnails(
    gallery_root: Path,
    metadata: Iterable[dict],
    *,
    force: bool = False,
    reporter: StatusReporter | None = None,
    max_workers: int | None = None,
) -> tuple[list[str], bool]:
    """Ensure thumbnails exist for each metadata entry.

    Returns a tuple of ``(processed_filenames, metadata_updated)``.
    """

    processed: list[str] = []
    updated = False
    images_dir = gallery_root / "images"

    if max_workers is not None and max_workers < 1:
        raise ValueError("max_workers must be at least 1")

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
        thumb_path_map = {
            size: gallery_root / rel for size, rel in thumb_rel_map.items()
        }
        need_create = force or any(
            not path.exists() for path in thumb_path_map.values()
        )
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

    if not pending:
        return processed, updated

    if max_workers == 1 or len(pending) == 1:
        for _filename, source, thumb_paths in pending:
            create_thumbnails(source, thumb_paths, reporter=reporter)
            if reporter is not None:
                reporter.advance()
        return processed, updated

    executor_kwargs: dict[str, object] = {}
    if max_workers is not None:
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
        executor_kwargs["mp_context"] = mp_context

    try:
        with ProcessPoolExecutor(**executor_kwargs) as executor:
            pending_iter = iter(pending)
            futures: set[concurrent.futures.Future] = set()

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
                )
                futures.add(future)
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
                future.result()
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
