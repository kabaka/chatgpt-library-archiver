import json
import os
import shutil
from datetime import datetime
from importlib import resources
from typing import Dict, List


def _load_all_metadata(gallery_root: str) -> List[Dict]:
    """Return a list of metadata entries from ``metadata.json``."""
    items: List[Dict] = []
    meta_path = os.path.join(gallery_root, "metadata.json")
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            items = json.load(f)
    return items


def _normalize_created_at(value) -> float | None:
    """Convert assorted ``created_at`` values into a float timestamp."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(text).timestamp()
            except ValueError:
                return None
    return None


def _created_at_key(value) -> float:
    """Return a sortable timestamp for ``created_at`` values."""

    normalized = _normalize_created_at(value)
    return normalized if normalized is not None else 0.0


def generate_gallery(gallery_root: str = "gallery") -> int:
    """Write ``metadata.json`` and copy bundled ``index.html`` for the gallery.

    The bundled viewer supports filtering by title and date range.
    """
    os.makedirs(gallery_root, exist_ok=True)
    items = _load_all_metadata(gallery_root)
    if not items:
        return 0

    for item in items:
        if "created_at" in item:
            normalized = _normalize_created_at(item.get("created_at"))
            item["created_at"] = normalized if normalized is not None else 0.0

    items.sort(
        key=lambda x: (_created_at_key(x.get("created_at")), x.get("id", "")),
        reverse=True,
    )
    meta_path = os.path.join(gallery_root, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)

    index_src = resources.open_binary("chatgpt_library_archiver", "gallery_index.html")
    with index_src as src, open(os.path.join(gallery_root, "index.html"), "wb") as dst:
        shutil.copyfileobj(src, dst)

    return len(items)


if __name__ == "__main__":
    total = generate_gallery()
    if total:
        print(f"Generated gallery with {total} images.")
    else:
        print("No gallery generated (no images found).")
