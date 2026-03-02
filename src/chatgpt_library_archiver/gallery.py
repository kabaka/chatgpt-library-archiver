from __future__ import annotations

import json
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


def _safe_json_for_html(items: list[GalleryItem]) -> str:
    """Serialize gallery items to JSON escaped for safe ``<script>`` embedding.

    After ``json.dumps`` the output is post-processed to replace ``<``, ``>``,
    and ``&`` with their Unicode escape sequences so that sequences like
    ``</script>`` cannot break out of the script block (XSS prevention).
    This follows the same approach used by Django's ``json_script`` filter.
    """
    raw = json.dumps(
        [item.to_dict() for item in items],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def generate_gallery(gallery_root: str = "gallery") -> int:
    """Write ``metadata.json`` and embed metadata into ``index.html``.

    ``metadata.json`` is still written for CLI tools that read it directly.
    The gallery viewer reads from a ``GALLERY_DATA`` variable injected into
    the HTML ``<head>`` so no runtime ``fetch()`` is required.
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

    template = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    escaped_json = _safe_json_for_html(items)
    data_script = f"<script>var GALLERY_DATA = {escaped_json};</script>"
    html = template.replace("</head>", f"{data_script}\n</head>", 1)
    (Path(gallery_root) / "index.html").write_text(html, encoding="utf-8")

    return len(items)


if __name__ == "__main__":
    total = generate_gallery()
    if total:
        print(f"Generated gallery with {total} images.")
    else:
        print("No gallery generated (no images found).")
