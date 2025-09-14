import json
import os
import shutil
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


def generate_gallery(gallery_root: str = "gallery") -> int:
    """Write ``metadata.json`` and copy bundled ``index.html`` for the gallery."""
    os.makedirs(gallery_root, exist_ok=True)
    items = _load_all_metadata(gallery_root)
    if not items:
        return 0

    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
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
