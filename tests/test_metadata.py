import json
from datetime import datetime
from pathlib import Path

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
