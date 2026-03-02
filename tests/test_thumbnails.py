import io
import multiprocessing
import queue
from concurrent.futures import Future
from pathlib import Path

import pytest
from PIL import Image

from chatgpt_library_archiver import thumbnails


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

    metadata = [{"filename": name} for name in filenames]

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_create_thumbnails(source, dest_map, reporter=None):
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

    assert executor_kwargs == [{"max_workers": PARALLEL_WORKERS}]
    assert len(submitted) == PARALLEL_WORKERS
    assert sorted(name for name, _ in calls) == sorted(filenames)
    assert processed == filenames
    assert updated
    for entry, name in zip(metadata, filenames, strict=True):
        assert entry["thumbnail"] == f"thumbs/medium/{name}"
        thumbs = entry["thumbnails"]
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

    metadata = [{"filename": name} for name in filenames]

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

    metadata = [{"filename": name} for name in filenames]
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
        assert entry["thumbnail"] == f"thumbs/medium/{name}"
        for size in thumbnails.THUMBNAIL_SIZES:
            rel_path = entry["thumbnails"][size]
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

    metadata = [{"filename": "good.png"}, {"filename": "bad.png"}]
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
    metadata = [{"filename": "foo.png"}, {"filename": "bar.jpg"}]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)

    assert changed is True
    for entry in metadata:
        name = entry["filename"]
        assert entry["thumbnail"] == f"thumbs/medium/{name}"
        assert entry["thumbnails"] == {
            "small": f"thumbs/small/{name}",
            "medium": f"thumbs/medium/{name}",
            "large": f"thumbs/large/{name}",
        }


def test_ensure_thumbnail_metadata_noop_when_already_correct():
    """Returns False when every entry already has the correct paths."""
    metadata = [
        {
            "filename": "img.png",
            "thumbnail": "thumbs/medium/img.png",
            "thumbnails": {
                "small": "thumbs/small/img.png",
                "medium": "thumbs/medium/img.png",
                "large": "thumbs/large/img.png",
            },
        }
    ]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)
    assert changed is False


def test_ensure_thumbnail_metadata_fixes_partial_mismatch():
    """Only the incorrect field is overwritten; returns True."""
    metadata = [
        {
            "filename": "pic.jpg",
            "thumbnail": "wrong/path.jpg",
            "thumbnails": {
                "small": "thumbs/small/pic.jpg",
                "medium": "thumbs/medium/pic.jpg",
                "large": "thumbs/large/pic.jpg",
            },
        }
    ]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)
    assert changed is True
    assert metadata[0]["thumbnail"] == "thumbs/medium/pic.jpg"


def test_ensure_thumbnail_metadata_skips_entries_without_filename():
    """Entries lacking a filename are silently skipped."""
    metadata = [{"title": "no filename"}, {"filename": "has.png"}]
    changed = thumbnails.ensure_thumbnail_metadata(Path("/unused"), metadata)
    assert changed is True
    assert "thumbnails" not in metadata[0]
    assert metadata[1]["thumbnail"] == "thumbs/medium/has.png"


def test_ensure_thumbnail_metadata_no_io(tmp_path):
    """The function must not check file existence or create directories."""
    # gallery_root points to a real dir but images/ does not exist
    metadata = [{"filename": "nonexistent.png"}]
    changed = thumbnails.ensure_thumbnail_metadata(tmp_path, metadata)
    assert changed is True
    # No directories were created
    assert not (tmp_path / "images").exists()
    assert not (tmp_path / "thumbs").exists()
