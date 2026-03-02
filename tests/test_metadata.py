import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from chatgpt_library_archiver import metadata


def test_normalize_created_at_numeric_and_iso() -> None:
    assert metadata.normalize_created_at(12) == pytest.approx(12.0)

    iso_value = "2024-01-01T12:30:00Z"
    expected = datetime.fromisoformat("2024-01-01T12:30:00+00:00").timestamp()
    assert metadata.normalize_created_at(iso_value) == pytest.approx(expected)


def test_normalize_created_at_blank() -> None:
    assert metadata.normalize_created_at("   ") is None


def test_gallery_item_from_dict_filters_extras(tmp_path: Path) -> None:
    raw = {
        "id": "1",
        "filename": "image.png",
        "tags": ["a", "b"],
        "thumbnails": {"small": "s.png", "medium": "m.png"},
        "extra_field": "value",
    }
    item = metadata.GalleryItem.from_dict(raw)
    assert item.id == "1"
    assert item.tags == ["a", "b"]
    assert item.thumbnails == {"small": "s.png", "medium": "m.png"}
    assert item.extra == {"extra_field": "value"}

    dest = tmp_path / "metadata.json"
    metadata.save_gallery_items(tmp_path, [item])
    assert json.loads(dest.read_text())[0]["id"] == "1"

    loaded = metadata.load_gallery_items(tmp_path)
    assert [loaded_item.id for loaded_item in loaded] == ["1"]


def test_save_gallery_items_is_atomic(tmp_path: Path) -> None:
    """Verify save uses a temp file + os.replace for atomic writes."""
    item = metadata.GalleryItem(id="a1", filename="pic.png")
    metadata.save_gallery_items(tmp_path, [item])

    dest = tmp_path / "metadata.json"
    data = json.loads(dest.read_text())
    assert data[0]["id"] == "a1"


def test_save_gallery_items_cleans_up_on_failure(tmp_path: Path) -> None:
    """On write failure the temp file is removed."""
    item = metadata.GalleryItem(id="b1", filename="fail.png")

    with (
        patch(
            "chatgpt_library_archiver.metadata.json.dumps",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        metadata.save_gallery_items(tmp_path, [item])

    # No temp files should be left behind
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []
    # metadata.json should not exist (never created)
    assert not (tmp_path / "metadata.json").exists()


def test_save_gallery_items_preserves_existing_on_failure(tmp_path: Path) -> None:
    """If save fails, the existing metadata.json is untouched."""
    item = metadata.GalleryItem(id="orig", filename="orig.png")
    metadata.save_gallery_items(tmp_path, [item])

    dest = tmp_path / "metadata.json"
    original_content = dest.read_text()

    def bad_dumps(*args, **kwargs):
        raise OSError("disk full")

    with (
        patch(
            "chatgpt_library_archiver.metadata.json.dumps",
            side_effect=bad_dumps,
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        metadata.save_gallery_items(
            tmp_path,
            [metadata.GalleryItem(id="new", filename="new.png")],
        )

    # Original file should be unchanged
    assert dest.read_text() == original_content


# ---------------------------------------------------------------------------
# 10.1 — Corrupt / malformed metadata JSON tests
# ---------------------------------------------------------------------------


def test_load_gallery_items_truncated_json_raises(tmp_path: Path) -> None:
    """Truncated JSON raises JSONDecodeError."""
    (tmp_path / "metadata.json").write_text('[{"id": "1", "filename": "a.png"')
    with pytest.raises(json.JSONDecodeError):
        metadata.load_gallery_items(tmp_path)


def test_load_gallery_items_dict_root_returns_empty_list(tmp_path: Path) -> None:
    """Non-list root (a dict) should return an empty list.

    Iterating a dict yields its keys (strings), which are not Mapping
    instances, so the ``isinstance`` guard filters them all out.
    """
    (tmp_path / "metadata.json").write_text('{"key": "value"}')
    items = metadata.load_gallery_items(tmp_path)
    assert items == []


def test_load_gallery_items_non_dict_items_in_list_are_filtered(
    tmp_path: Path,
) -> None:
    """Non-Mapping items in the JSON list are silently skipped."""
    data = [
        {"id": "1", "filename": "a.png"},
        "just a string",
        42,
        None,
        {"id": "2", "filename": "b.png"},
    ]
    (tmp_path / "metadata.json").write_text(json.dumps(data))
    items = metadata.load_gallery_items(tmp_path)
    assert len(items) == 2
    assert items[0].id == "1"
    assert items[1].id == "2"


def test_load_gallery_items_missing_id_and_filename_default_to_empty(
    tmp_path: Path,
) -> None:
    """Items missing 'id' or 'filename' default to empty strings via from_dict."""
    data = [{"tags": ["a"]}]
    (tmp_path / "metadata.json").write_text(json.dumps(data))
    items = metadata.load_gallery_items(tmp_path)
    assert len(items) == 1
    assert items[0].id == ""
    assert items[0].filename == ""
    assert items[0].tags == ["a"]
