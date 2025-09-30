import io

import pytest
from PIL import Image

from chatgpt_library_archiver import thumbnails


def _sample_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


PNG_BYTES = _sample_png_bytes()


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

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, D401
            return False

        def submit(self, fn, *args):  # noqa: ANN001
            submitted.append(args)
            return DummyFuture(fn, *args)

    def fake_as_completed(futures):  # noqa: ANN001
        for future in list(futures):
            yield future

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


def test_regenerate_thumbnails_rejects_invalid_worker_count(tmp_path):
    with pytest.raises(ValueError):
        thumbnails.regenerate_thumbnails(tmp_path, [], max_workers=0)
