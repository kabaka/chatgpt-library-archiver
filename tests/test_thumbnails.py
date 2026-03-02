import io
import multiprocessing
import os
import queue
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from chatgpt_library_archiver import thumbnails
from chatgpt_library_archiver.metadata import GalleryItem


def test_max_image_pixels_is_set():
    """Decompression bomb guard must be active at module scope (M-4)."""
    assert Image.MAX_IMAGE_PIXELS == 200_000_000


PARALLEL_WORKERS = 2


class RecordingReporter:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.errors: list[tuple] = []
        self.total: int = 0
        self.advanced: int = 0

    def log_status(self, action: str, detail: str) -> None:
        self.messages.append((action, detail))

    def add_total(self, amount: int) -> None:
        self.total += amount

    def report_error(self, action, detail, *, reason="", context=None, exception=None):
        self.errors.append((action, detail, reason))

    def advance(self, amount: int = 1) -> None:
        self.advanced += amount


def test_create_thumbnails_logs_start_and_finish(tmp_path, sample_png_bytes):
    source = tmp_path / "image.png"
    source.write_bytes(sample_png_bytes)
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}

    reporter = RecordingReporter()

    thumbnails.create_thumbnails(source, dest_map, reporter=reporter)

    assert reporter.messages == [
        ("Generating thumbnails for", "image.png"),
        ("Finished generating thumbnails for", "image.png"),
    ]


def test_regenerate_thumbnails_parallel_uses_executor(
    monkeypatch, tmp_path, sample_png_bytes
):
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()

    filenames = ["one.png", "two.png"]
    for name in filenames:
        (images_dir / name).write_bytes(sample_png_bytes)

    metadata = [GalleryItem(id=name, filename=name) for name in filenames]

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_create_thumbnails(source, dest_map, reporter=None, webp=False):
        calls.append((source.name, dest_map))

    monkeypatch.setattr(thumbnails, "create_thumbnails", fake_create_thumbnails)

    executor_kwargs: list[dict[str, object]] = []
    submitted: list[tuple] = []

    class DummyFuture:
        def __init__(self, fn, *args):
            self._fn = fn
            self._args = args

        def result(self):
            return self._fn(*self._args)

    class DummyExecutor:
        def __init__(self, **kwargs):
            executor_kwargs.append(kwargs)
            self._max_workers = kwargs.get("max_workers", PARALLEL_WORKERS)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args):
            submitted.append(args)
            return DummyFuture(fn, *args)

    def fake_as_completed(futures):
        yield from list(futures)

    monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr(thumbnails, "as_completed", fake_as_completed)

    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_root,
        metadata,
        force=True,
        max_workers=PARALLEL_WORKERS,
    )

    assert executor_kwargs == [{"max_workers": PARALLEL_WORKERS, "mp_context": None}]
    assert len(submitted) == PARALLEL_WORKERS
    assert sorted(name for name, _ in calls) == sorted(filenames)
    assert processed == filenames
    assert updated
    for entry, name in zip(metadata, filenames, strict=True):
        assert entry.thumbnail == f"thumbs/medium/{name}"
        thumbs = entry.thumbnails
        assert thumbs["small"] == f"thumbs/small/{name}"
        assert thumbs["medium"] == f"thumbs/medium/{name}"
        assert thumbs["large"] == f"thumbs/large/{name}"


def test_regenerate_thumbnails_parallel_reports_start_and_finish(
    monkeypatch, tmp_path, sample_png_bytes
):
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()

    filenames = ["one.png", "two.png", "three.png"]
    for name in filenames:
        (images_dir / name).write_bytes(sample_png_bytes)

    metadata = [GalleryItem(id=name, filename=name) for name in filenames]

    executor_kwargs: list[dict[str, object]] = []

    class DummyFuture(Future):
        def __init__(self, fn, *args):
            super().__init__()
            try:
                result = fn(*args)
            except Exception as exc:
                self.set_exception(exc)
            else:
                self.set_result(result)

    class DummyExecutor:
        def __init__(self, **kwargs):
            executor_kwargs.append(kwargs)
            self._max_workers = kwargs.get("max_workers", PARALLEL_WORKERS)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args):
            return DummyFuture(fn, *args)

    class DummyManager:
        def __init__(self) -> None:
            self.queue = queue.Queue()
            self.shutdown_called = False

        def Queue(self):
            return self.queue

        def shutdown(self) -> None:
            self.shutdown_called = True

    class DummyContext:
        def __init__(self) -> None:
            self.manager = DummyManager()

        def Manager(self) -> DummyManager:
            return self.manager

    reporter = RecordingReporter()

    monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", DummyExecutor)
    dummy_context = DummyContext()
    monkeypatch.setattr(
        thumbnails.multiprocessing, "get_context", lambda: dummy_context
    )

    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_root,
        metadata,
        force=True,
        reporter=reporter,
        max_workers=PARALLEL_WORKERS,
    )

    assert len(executor_kwargs) == 1
    kwargs = executor_kwargs[0]
    assert kwargs.get("max_workers") == PARALLEL_WORKERS
    assert isinstance(kwargs.get("mp_context"), DummyContext)
    assert sorted(processed) == sorted(filenames)
    assert updated
    assert reporter.total == len(filenames)
    assert reporter.advanced == len(filenames)

    assert dummy_context.manager.shutdown_called

    starts = {
        detail
        for action, detail in reporter.messages
        if action == "Generating thumbnails for"
    }
    finishes = {
        detail
        for action, detail in reporter.messages
        if action == "Finished generating thumbnails for"
    }
    assert starts == finishes == set(filenames)

    positions = {message: idx for idx, message in enumerate(reporter.messages)}
    for name in filenames:
        start_key = ("Generating thumbnails for", name)
        finish_key = ("Finished generating thumbnails for", name)
        assert positions[start_key] < positions[finish_key]


def test_regenerate_thumbnails_rejects_invalid_worker_count(tmp_path):
    with pytest.raises(ValueError):
        thumbnails.regenerate_thumbnails(tmp_path, [], max_workers=0)


def test_regenerate_thumbnails_parallel_with_spawn_queue(
    tmp_path, monkeypatch, sample_png_bytes
):
    try:
        spawn_context = multiprocessing.get_context("spawn")
    except ValueError:  # pragma: no cover - safety for unusual platforms
        pytest.skip("spawn start method not available")

    monkeypatch.setattr(
        thumbnails.multiprocessing, "get_context", lambda: spawn_context
    )

    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()

    filenames = ["alpha.png", "beta.png", "gamma.png"]
    for name in filenames:
        (images_dir / name).write_bytes(sample_png_bytes)

    metadata = [GalleryItem(id=name, filename=name) for name in filenames]
    reporter = RecordingReporter()

    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_root,
        metadata,
        force=True,
        reporter=reporter,
        max_workers=2,
    )

    assert sorted(processed) == sorted(filenames)
    assert updated
    assert reporter.total == len(filenames)
    assert reporter.advanced == len(filenames)

    for entry, name in zip(metadata, filenames, strict=True):
        assert entry.thumbnail == f"thumbs/medium/{name}"
        for size in thumbnails.THUMBNAIL_SIZES:
            rel_path = entry.thumbnails[size]
            expected_rel = f"thumbs/{size}/{name}"
            assert rel_path == expected_rel
            dest_path = gallery_root / rel_path
            assert dest_path.is_file()


# --- Error-path tests (item 4.3) ---


def test_create_thumbnails_missing_source_raises_thumbnail_error(tmp_path):
    """create_thumbnails must raise ThumbnailError for a non-existent source."""
    source = tmp_path / "nonexistent.png"
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}

    with pytest.raises(thumbnails.ThumbnailError):
        thumbnails.create_thumbnails(source, dest_map)


def test_create_thumbnails_corrupt_image_raises_thumbnail_error(tmp_path):
    """create_thumbnails must raise ThumbnailError for an unreadable image."""
    source = tmp_path / "corrupt.png"
    source.write_bytes(b"\x00garbage\xff\xfe")
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}

    with pytest.raises(thumbnails.ThumbnailError):
        thumbnails.create_thumbnails(source, dest_map)


@pytest.mark.parametrize("max_workers", [1, 2])
def test_regenerate_thumbnails_one_bad_one_good_continues_and_reports_error(
    monkeypatch,
    gallery_dir,
    sample_png_bytes,
    max_workers,
):
    """Batch continues past a corrupt image and reports the error."""
    images_dir = gallery_dir / "images"
    (images_dir / "good.png").write_bytes(sample_png_bytes)
    (images_dir / "bad.png").write_bytes(b"\x00garbage\xff\xfe")

    metadata = [
        GalleryItem(id="good", filename="good.png"),
        GalleryItem(id="bad", filename="bad.png"),
    ]
    reporter = RecordingReporter()

    if max_workers == 2:

        class _DummyFuture(Future):
            def __init__(self, fn, *args):
                super().__init__()
                try:
                    result = fn(*args)
                except Exception as exc:
                    self.set_exception(exc)
                else:
                    self.set_result(result)

        class _DummyExecutor:
            def __init__(self, **kwargs):
                self._max_workers = kwargs.get("max_workers", 2)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def submit(self, fn, *args):
                return _DummyFuture(fn, *args)

        class _DummyManager:
            def __init__(self):
                self.queue = queue.Queue()
                self.shutdown_called = False

            def Queue(self):
                return self.queue

            def shutdown(self):
                self.shutdown_called = True

        class _DummyContext:
            def __init__(self):
                self.manager = _DummyManager()

            def Manager(self):
                return self.manager

        monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", _DummyExecutor)
        dummy_ctx = _DummyContext()
        monkeypatch.setattr(
            thumbnails.multiprocessing,
            "get_context",
            lambda: dummy_ctx,
        )

    processed, _updated = thumbnails.regenerate_thumbnails(
        gallery_dir,
        metadata,
        force=True,
        reporter=reporter,
        max_workers=max_workers,
    )

    # Both images are in the processed list
    assert "good.png" in processed
    assert "bad.png" in processed

    # Good image's thumbnails were created
    for size in thumbnails.THUMBNAIL_SIZES:
        assert (gallery_dir / "thumbs" / size / "good.png").is_file()

    # Reporter collected exactly one error for the bad image
    assert len(reporter.errors) == 1
    _action, detail, reason = reporter.errors[0]
    assert "bad.png" in detail
    assert reason  # non-empty reason string

    # Both images advanced the progress counter
    assert reporter.advanced == 2


# ---------------------------------------------------------------------------
# 10.4 — Thumbnail format-specific tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt,ext",
    [
        ("WEBP", ".webp"),
        ("GIF", ".gif"),
        ("BMP", ".bmp"),
    ],
)
def test_create_thumbnails_format_specific(tmp_path, fmt, ext):
    """Format-specific _prepare_for_format branches are exercised."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(100, 150, 200)).save(buf, format=fmt)
    source = tmp_path / f"image{ext}"
    source.write_bytes(buf.getvalue())

    dest_map = {size: tmp_path / f"{size}{ext}" for size in thumbnails.THUMBNAIL_SIZES}
    thumbnails.create_thumbnails(source, dest_map)

    for size, dest in dest_map.items():
        assert dest.is_file(), f"{size} thumbnail was not created for {fmt}"
        with Image.open(dest) as img:
            assert img.size[0] <= 400 and img.size[1] <= 400


def test_create_thumbnails_rgba_to_rgb_jpeg_conversion(tmp_path):
    """RGBA image saved as JPEG thumbnail must convert to RGB mode."""
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), color=(100, 150, 200, 128)).save(buf, format="PNG")
    source = tmp_path / "rgba_image.png"
    source.write_bytes(buf.getvalue())

    dest_map = {size: tmp_path / f"{size}.jpg" for size in thumbnails.THUMBNAIL_SIZES}
    thumbnails.create_thumbnails(source, dest_map)

    for size, dest in dest_map.items():
        assert dest.is_file(), f"{size} JPEG thumbnail was not created"
        with Image.open(dest) as img:
            assert img.mode == "RGB", (
                f"{size} thumbnail has mode {img.mode}, expected RGB"
            )


# ---------------------------------------------------------------------------
# 12.4 — ensure_thumbnail_metadata() tests
# ---------------------------------------------------------------------------


def test_ensure_thumbnail_metadata_sets_missing_fields():
    """Entries without thumbnails/thumbnail get the correct paths."""
    metadata = [
        GalleryItem(id="foo", filename="foo.png"),
        GalleryItem(id="bar", filename="bar.jpg"),
    ]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)

    assert changed is True
    for entry in metadata:
        name = entry.filename
        assert entry.thumbnail == f"thumbs/medium/{name}"
        assert entry.thumbnails == {
            "small": f"thumbs/small/{name}",
            "medium": f"thumbs/medium/{name}",
            "large": f"thumbs/large/{name}",
        }


def test_ensure_thumbnail_metadata_noop_when_already_correct():
    """Returns False when every entry already has the correct paths."""
    metadata = [
        GalleryItem(
            id="img",
            filename="img.png",
            thumbnail="thumbs/medium/img.png",
            thumbnails={
                "small": "thumbs/small/img.png",
                "medium": "thumbs/medium/img.png",
                "large": "thumbs/large/img.png",
            },
        )
    ]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)
    assert changed is False


def test_ensure_thumbnail_metadata_fixes_partial_mismatch():
    """Only the incorrect field is overwritten; returns True."""
    metadata = [
        GalleryItem(
            id="pic",
            filename="pic.jpg",
            thumbnail="wrong/path.jpg",
            thumbnails={
                "small": "thumbs/small/pic.jpg",
                "medium": "thumbs/medium/pic.jpg",
                "large": "thumbs/large/pic.jpg",
            },
        )
    ]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)
    assert changed is True
    assert metadata[0].thumbnail == "thumbs/medium/pic.jpg"


def test_ensure_thumbnail_metadata_skips_entries_without_filename():
    """Entries lacking a filename are silently skipped."""
    metadata = [
        GalleryItem(id="no-file", filename=""),
        GalleryItem(id="has", filename="has.png"),
    ]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)
    assert changed is True
    assert metadata[0].thumbnails == {}
    assert metadata[1].thumbnail == "thumbs/medium/has.png"


def test_ensure_thumbnail_metadata_no_io(tmp_path):
    """The function must not check file existence or create directories."""
    # gallery_root points to a real dir but images/ does not exist
    metadata = [GalleryItem(id="missing", filename="nonexistent.png")]
    changed = thumbnails.ensure_thumbnail_metadata(tmp_path, metadata)
    assert changed is True
    # No directories were created
    assert not (tmp_path / "images").exists()
    assert not (tmp_path / "thumbs").exists()


# ---------------------------------------------------------------------------
# 13.2 — max_workers cap
# ---------------------------------------------------------------------------


def test_regenerate_thumbnails_caps_max_workers_at_8(
    monkeypatch, tmp_path, sample_png_bytes
):
    """When max_workers is None, it should default to min(cpu_count, 8)."""
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()
    for name in ("a.png", "b.png"):
        (images_dir / name).write_bytes(sample_png_bytes)

    metadata = [
        GalleryItem(id="a", filename="a.png"),
        GalleryItem(id="b", filename="b.png"),
    ]

    executor_kwargs_log: list[dict[str, object]] = []

    class DummyFuture:
        def __init__(self, fn, *args):
            self._fn = fn
            self._args = args

        def result(self):
            return self._fn(*self._args)

    class DummyExecutor:
        def __init__(self, **kwargs):
            executor_kwargs_log.append(kwargs)
            self._max_workers = kwargs.get("max_workers", 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, *args):
            return DummyFuture(fn, *args)

    def fake_as_completed(futures):
        yield from list(futures)

    monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr(thumbnails, "as_completed", fake_as_completed)

    # Simulate 64-core machine
    with patch.object(os, "cpu_count", return_value=64):
        thumbnails.regenerate_thumbnails(
            gallery_root,
            metadata,
            force=True,
            max_workers=None,
        )

    assert executor_kwargs_log[0]["max_workers"] == 8


def test_regenerate_thumbnails_caps_max_workers_low_cpu(
    monkeypatch, tmp_path, sample_png_bytes
):
    """When cpu_count is 2, max_workers should be 2 (not capped to 8)."""
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()
    for name in ("a.png", "b.png"):
        (images_dir / name).write_bytes(sample_png_bytes)

    metadata = [
        GalleryItem(id="a", filename="a.png"),
        GalleryItem(id="b", filename="b.png"),
    ]

    executor_kwargs_log: list[dict[str, object]] = []

    class DummyFuture:
        def __init__(self, fn, *args):
            self._fn = fn
            self._args = args

        def result(self):
            return self._fn(*self._args)

    class DummyExecutor:
        def __init__(self, **kwargs):
            executor_kwargs_log.append(kwargs)
            self._max_workers = kwargs.get("max_workers", 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, *args):
            return DummyFuture(fn, *args)

    def fake_as_completed(futures):
        yield from list(futures)

    monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr(thumbnails, "as_completed", fake_as_completed)

    with patch.object(os, "cpu_count", return_value=2):
        thumbnails.regenerate_thumbnails(
            gallery_root,
            metadata,
            force=True,
            max_workers=None,
        )

    assert executor_kwargs_log[0]["max_workers"] == 2


# ---------------------------------------------------------------------------
# 13.3 — mtime-based freshness check
# ---------------------------------------------------------------------------


def test_regenerate_thumbnails_recreates_stale_thumbnails(
    gallery_dir, sample_png_bytes
):
    """Thumbnails older than their source image are regenerated."""
    images_dir = gallery_dir / "images"
    source = images_dir / "img.png"
    source.write_bytes(sample_png_bytes)

    metadata = [GalleryItem(id="img", filename="img.png")]

    # First pass — create thumbnails
    thumbnails.regenerate_thumbnails(gallery_dir, metadata, force=True, max_workers=1)

    for size in thumbnails.THUMBNAIL_SIZES:
        assert (gallery_dir / "thumbs" / size / "img.png").is_file()

    # Record original mtime of a thumbnail
    thumb_path = gallery_dir / "thumbs" / "medium" / "img.png"
    old_mtime = thumb_path.stat().st_mtime

    # Touch the source so it's newer than thumbnails
    time.sleep(0.05)
    source.write_bytes(sample_png_bytes)

    # Second pass — should detect staleness and regenerate
    thumbnails.regenerate_thumbnails(gallery_dir, metadata, force=False, max_workers=1)

    new_mtime = thumb_path.stat().st_mtime
    assert new_mtime > old_mtime, "Stale thumbnail should have been regenerated"


# ---------------------------------------------------------------------------
# 13.4 — RGBA → RGB white background compositing
# ---------------------------------------------------------------------------


def test_rgba_to_rgb_jpeg_has_white_background(tmp_path):
    """RGBA PNG saved as JPEG should composite onto white, not black."""
    # Create a fully transparent RGBA image
    rgba_img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    buf = io.BytesIO()
    rgba_img.save(buf, format="PNG")
    source = tmp_path / "transparent.png"
    source.write_bytes(buf.getvalue())

    dest_map = {size: tmp_path / f"{size}.jpg" for size in thumbnails.THUMBNAIL_SIZES}
    thumbnails.create_thumbnails(source, dest_map)

    for size, dest in dest_map.items():
        assert dest.is_file()
        with Image.open(dest) as img:
            assert img.mode == "RGB"
            # Transparent regions should be white (255, 255, 255)
            corner = img.getpixel((0, 0))
            assert corner == (255, 255, 255), (
                f"{size} thumbnail corner pixel is {corner}, expected (255, 255, 255)"
            )


# ---------------------------------------------------------------------------
# WebP thumbnail output tests
# ---------------------------------------------------------------------------


def test_thumbnail_relative_path_webp():
    """webp=True replaces the file extension with .webp."""
    assert thumbnails.thumbnail_relative_path("image.png", "small", webp=True) == (
        "thumbs/small/image.webp"
    )
    assert thumbnails.thumbnail_relative_path("photo.jpg", "medium", webp=True) == (
        "thumbs/medium/photo.webp"
    )


def test_thumbnail_relative_path_webp_false_preserves_extension():
    """webp=False keeps the original extension."""
    assert thumbnails.thumbnail_relative_path("image.png", "small", webp=False) == (
        "thumbs/small/image.png"
    )


def test_thumbnail_relative_paths_webp():
    """All paths use .webp extensions when webp=True."""
    paths = thumbnails.thumbnail_relative_paths("photo.jpg", webp=True)
    for size in thumbnails.THUMBNAIL_SIZES:
        assert paths[size] == f"thumbs/{size}/photo.webp"


def test_create_thumbnails_webp_output(tmp_path, sample_png_bytes):
    """webp=True saves all thumbnails as WebP regardless of source format."""
    source = tmp_path / "image.png"
    source.write_bytes(sample_png_bytes)

    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}
    thumbnails.create_thumbnails(source, dest_map, webp=True)

    for size in thumbnails.THUMBNAIL_SIZES:
        webp_dest = tmp_path / f"{size}.webp"
        assert webp_dest.is_file(), f"{size} WebP thumbnail was not created"
        with Image.open(webp_dest) as img:
            assert img.format == "WEBP"


def test_create_thumbnails_webp_from_jpeg(tmp_path):
    """JPEG source produces WebP thumbnails when webp=True."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(50, 100, 150)).save(buf, format="JPEG")
    source = tmp_path / "photo.jpg"
    source.write_bytes(buf.getvalue())

    dest_map = {size: tmp_path / f"{size}.jpg" for size in thumbnails.THUMBNAIL_SIZES}
    thumbnails.create_thumbnails(source, dest_map, webp=True)

    for size in thumbnails.THUMBNAIL_SIZES:
        webp_dest = tmp_path / f"{size}.webp"
        assert webp_dest.is_file()
        with Image.open(webp_dest) as img:
            assert img.format == "WEBP"


def test_ensure_thumbnail_metadata_webp():
    """ensure_thumbnail_metadata uses .webp paths when webp=True."""
    metadata = [GalleryItem(id="photo", filename="photo.jpg")]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata, webp=True)
    assert changed is True
    assert metadata[0].thumbnail == "thumbs/medium/photo.webp"
    for size in thumbnails.THUMBNAIL_SIZES:
        assert metadata[0].thumbnails[size] == f"thumbs/{size}/photo.webp"


def test_regenerate_thumbnails_webp_creates_webp_files(gallery_dir, sample_png_bytes):
    """regenerate_thumbnails with webp=True creates .webp thumbnail files."""
    images_dir = gallery_dir / "images"
    (images_dir / "img.png").write_bytes(sample_png_bytes)

    metadata = [GalleryItem(id="img", filename="img.png")]
    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_dir,
        metadata,
        force=True,
        max_workers=1,
        webp=True,
    )

    assert "img.png" in processed
    assert updated
    for size in thumbnails.THUMBNAIL_SIZES:
        webp_path = gallery_dir / "thumbs" / size / "img.webp"
        assert webp_path.is_file(), f"WebP thumbnail missing for {size}"
        with Image.open(webp_path) as img:
            assert img.format == "WEBP"

    # Metadata should reference .webp paths
    assert metadata[0].thumbnail == "thumbs/medium/img.webp"
    for size in thumbnails.THUMBNAIL_SIZES:
        assert metadata[0].thumbnails[size] == f"thumbs/{size}/img.webp"


# ---------------------------------------------------------------------------
# ICC profile handling tests
# ---------------------------------------------------------------------------


def _make_image_with_icc(
    mode: str = "RGB",
    size: tuple[int, int] = (8, 8),
    color: tuple[int, ...] = (100, 150, 200),
    profile_desc: str = "sRGB",
) -> Image.Image:
    """Helper: create an image with an ICC profile attached."""
    from PIL import ImageCms

    img = Image.new(mode, size, color)
    if profile_desc.lower() == "srgb":
        profile = ImageCms.createProfile("sRGB")
    else:
        # Use sRGB bytes but we'll mock the description to simulate non-sRGB.
        profile = ImageCms.createProfile("sRGB")
    img.info["icc_profile"] = ImageCms.ImageCmsProfile(profile).tobytes()
    return img


def test_ensure_srgb_no_profile():
    """Image without ICC profile is returned unchanged."""
    img = Image.new("RGB", (8, 8), (100, 150, 200))
    result = thumbnails._ensure_srgb(img)
    assert "icc_profile" not in result.info
    assert result is img


def test_ensure_srgb_strips_srgb_profile():
    """sRGB profile is stripped without colour conversion."""
    img = _make_image_with_icc(profile_desc="sRGB")
    assert "icc_profile" in img.info

    result = thumbnails._ensure_srgb(img)
    assert "icc_profile" not in result.info


def test_ensure_srgb_converts_non_srgb_profile(monkeypatch):
    """Non-sRGB profile triggers colour conversion and profile stripping."""
    from PIL import ImageCms

    img = _make_image_with_icc(profile_desc="sRGB")
    assert "icc_profile" in img.info

    # Mock description to simulate a non-sRGB profile (e.g., Display P3).
    monkeypatch.setattr(ImageCms, "getProfileDescription", lambda _p: "Display P3")

    result = thumbnails._ensure_srgb(img)
    assert "icc_profile" not in result.info
    assert result.mode == "RGB"


def test_ensure_srgb_converts_rgba_non_srgb(monkeypatch):
    """RGBA image with non-sRGB profile preserves alpha after conversion."""
    from PIL import ImageCms

    img = _make_image_with_icc(
        mode="RGBA", color=(100, 150, 200, 128), profile_desc="sRGB"
    )
    monkeypatch.setattr(ImageCms, "getProfileDescription", lambda _p: "Display P3")

    result = thumbnails._ensure_srgb(img)
    assert "icc_profile" not in result.info
    assert result.mode == "RGBA"
    # Alpha channel should be preserved.
    alpha = result.split()[3]
    assert alpha.getpixel((0, 0)) == 128


def test_ensure_srgb_corrupt_profile_strips_gracefully():
    """Corrupt ICC profile bytes are stripped without raising."""
    img = Image.new("RGB", (8, 8), (100, 150, 200))
    img.info["icc_profile"] = b"\x00corrupt\xff\xfe"

    result = thumbnails._ensure_srgb(img)
    assert "icc_profile" not in result.info


def test_create_thumbnails_strips_icc_profile(tmp_path):
    """End-to-end: ICC profile on source image is not propagated to thumbnails."""
    from PIL import ImageCms

    profile = ImageCms.createProfile("sRGB")
    profile_bytes = ImageCms.ImageCmsProfile(profile).tobytes()

    img = Image.new("RGB", (32, 32), (100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG", icc_profile=profile_bytes)
    source = tmp_path / "profiled.png"
    source.write_bytes(buf.getvalue())

    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}
    thumbnails.create_thumbnails(source, dest_map)

    for size, dest in dest_map.items():
        assert dest.is_file()
        with Image.open(dest) as thumb:
            assert not thumb.info.get("icc_profile"), (
                f"{size} thumbnail should not have an ICC profile"
            )
