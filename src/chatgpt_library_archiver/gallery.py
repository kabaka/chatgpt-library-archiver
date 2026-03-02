from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

from .metadata import (
    GalleryItem,
    created_at_sort_key,
    load_gallery_items,
    save_gallery_items,
)


def _created_at_key(item: GalleryItem) -> float:
    return created_at_sort_key(item.created_at)


def generate_gallery(gallery_root: str = "gallery") -> int:
    """Write ``metadata.json`` and copy bundled ``index.html`` for the gallery.

    The bundled viewer supports filtering by title and date range.
    """
    Path(gallery_root).mkdir(parents=True, exist_ok=True)
    items = load_gallery_items(gallery_root)
    if not items:
        return 0

    for item in items:
        if item.created_at is None:
            item.created_at = 0.0

    items.sort(
        key=lambda item: (_created_at_key(item), item.id),
        reverse=True,
    )
    save_gallery_items(gallery_root, items)

    index_src = resources.open_binary("chatgpt_library_archiver", "gallery_index.html")
    with index_src as src, (Path(gallery_root) / "index.html").open("wb") as dst:
        shutil.copyfileobj(src, dst)

    return len(items)


if __name__ == "__main__":
    total = generate_gallery()
    if total:
        print(f"Generated gallery with {total} images.")
    else:
        print("No gallery generated (no images found).")
