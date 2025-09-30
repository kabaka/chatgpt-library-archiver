import io
import queue
from concurrent.futures import Future

import pytest
from PIL import Image

from chatgpt_library_archiver import thumbnails


def _sample_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _sample_png_bytes()


class RecordingReporter:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.total: int = 0
        self.advanced: int = 0

    def log_status(self, action: str, detail: str) -> None:
        self.messages.append((action, detail))

    def add_total(self, amount: int) -> None:
        self.total += amount

    def advance(self, amount: int = 1) -> None:
        self.advanced += amount


def test_create_thumbnails_logs_start_and_finish(tmp_path):
    source = tmp_path / "image.png"
    source.write_bytes(PNG_BYTES)
    dest_map = {size: tmp_path / f"{size}.png" for size in thumbnails.THUMBNAIL_SIZES}

    reporter = RecordingReporter()

    thumbnails.create_thumbnails(source, dest_map, reporter=reporter)

    assert reporter.messages == [
        ("Generating thumbnails for", "image.png"),
        ("Finished generating thumbnails for", "image.png"),
    ]


def test_regenerate_thumbnails_parallel_uses_executor(monkeypatch, tmp_path):
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()

    filenames = ["one.png", "two.png"]
    for name in filenames:
        (images_dir / name).write_bytes(PNG_BYTES)

    metadata = [{"filename": name} for name in filenames]

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_create_thumbnails(source, dest_map, reporter=None):  # noqa: ANN001
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
            self._max_workers = kwargs.get("max_workers", 1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, D401
            return False

        def submit(self, fn, *args):  # noqa: ANN001
            submitted.append(args)
            return DummyFuture(fn, *args)

    def fake_as_completed(futures):  # noqa: ANN001
        yield from list(futures)

    monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr(thumbnails, "as_completed", fake_as_completed)

    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_root,
        metadata,
        force=True,
        max_workers=2,
    )

    assert executor_kwargs == [{"max_workers": 2}]
    assert len(submitted) == 2
    assert sorted(name for name, _ in calls) == sorted(filenames)
    assert processed == filenames
    assert updated
    for entry, name in zip(metadata, filenames, strict=True):
        assert entry["thumbnail"] == f"thumbs/medium/{name}"
        thumbs = entry["thumbnails"]
        assert thumbs["small"] == f"thumbs/small/{name}"
        assert thumbs["medium"] == f"thumbs/medium/{name}"
        assert thumbs["large"] == f"thumbs/large/{name}"


def test_regenerate_thumbnails_parallel_reports_start_and_finish(monkeypatch, tmp_path):
    gallery_root = tmp_path
    images_dir = gallery_root / "images"
    images_dir.mkdir()

    filenames = ["one.png", "two.png", "three.png"]
    for name in filenames:
        (images_dir / name).write_bytes(PNG_BYTES)

    metadata = [{"filename": name} for name in filenames]

    executor_kwargs: list[dict[str, object]] = []

    class DummyFuture(Future):
        def __init__(self, fn, *args):  # noqa: ANN001
            super().__init__()
            try:
                result = fn(*args)
            except Exception as exc:  # noqa: BLE001
                self.set_exception(exc)
            else:
                self.set_result(result)

    class DummyExecutor:
        def __init__(self, **kwargs):
            executor_kwargs.append(kwargs)
            self._max_workers = kwargs.get("max_workers", 2)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, D401
            return False

        def submit(self, fn, *args):  # noqa: ANN001
            return DummyFuture(fn, *args)

    class DummyContext:
        def Queue(self):  # noqa: D401, ANN001
            return queue.Queue()

    reporter = RecordingReporter()

    monkeypatch.setattr(thumbnails, "ProcessPoolExecutor", DummyExecutor)
    monkeypatch.setattr(
        thumbnails.multiprocessing, "get_context", lambda: DummyContext()
    )

    processed, updated = thumbnails.regenerate_thumbnails(
        gallery_root,
        metadata,
        force=True,
        reporter=reporter,
        max_workers=2,
    )

    assert len(executor_kwargs) == 1
    kwargs = executor_kwargs[0]
    assert kwargs.get("max_workers") == 2
    assert isinstance(kwargs.get("mp_context"), DummyContext)
    assert sorted(processed) == sorted(filenames)
    assert updated
    assert reporter.total == len(filenames)
    assert reporter.advanced == len(filenames)

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
