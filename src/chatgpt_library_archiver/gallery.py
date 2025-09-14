import json
import os
from datetime import datetime
from typing import Dict, List


def _load_all_metadata(gallery_root: str) -> List[Dict]:
    """Load all metadata entries from the gallery directory."""
    items: List[Dict] = []
    if not os.path.isdir(gallery_root):
        return items

    seen_ids = set()

    # Load unified metadata.json if present
    meta_path = os.path.join(gallery_root, "metadata.json")
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                entry = dict(item)
                entry["image_path"] = f"images/{item['filename']}"
                items.append(entry)
                seen_ids.add(item.get("id"))

    # Backward compatibility: also load legacy versioned folders
    versions = [
        d
        for d in os.listdir(gallery_root)
        if d.startswith("v") and os.path.isdir(os.path.join(gallery_root, d))
    ]
    for version in versions:
        meta_path = os.path.join(gallery_root, version, f"metadata_{version}.json")
        if not os.path.isfile(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                if item.get("id") in seen_ids:
                    continue
                entry = dict(item)
                entry["image_path"] = f"{version}/images/{item['filename']}"
                items.append(entry)
                seen_ids.add(item.get("id"))
    return items


def _generate_html(page_items: List[Dict], page_num: int, total_pages: int) -> str:
    html = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        f"<title>Gallery – Page {page_num}</title>",
        "<style>",
        "body { font-family: sans-serif; margin: 20px; background: white; "
        "color: black; transition: background 0.3s, color 0.3s; }",
        "body.dark { background: #111; color: #eee; }",
        ".gallery-grid { display: grid; gap: 15px; }",
        ".gallery-small { grid-template-columns: repeat(6, 1fr); }",
        ".gallery-medium { grid-template-columns: repeat(4, 1fr); }",
        ".gallery-large { grid-template-columns: repeat(2, 1fr); }",
        ".image-card { border: 1px solid #ccc; padding: 8px; border-radius: 8px; "
        "font-size: 0.85em; background: white; }",
        "body.dark .image-card { background: #222; }",
        "img { width: 100%; border-radius: 4px; display: block; }",
        ".meta { margin-top: 6px; color: #444; }",
        "body.dark .meta { color: #ccc; }",
        "h1 { margin-bottom: 10px; }",
        ".search-bar { margin-bottom: 15px; display: flex; gap: 10px; "
        "align-items: center; }",
        ".search-bar input { padding: 6px; font-size: 1em; width: 300px; }",
        ".controls { display: flex; justify-content: flex-end; gap: 10px; "
        "margin-bottom: 15px; }",
        ".toggle { background: #ddd; border-radius: 5px; padding: 6px 10px; "
        "cursor: pointer; font-size: 0.9em; }",
        "body.dark .toggle { background: #555; color: white; }",
        ".size-select { background: #ddd; border-radius: 5px; padding: 6px 10px; "
        "cursor: pointer; font-size: 0.9em; }",
        "body.dark .size-select { background: #555; color: white; }",
        "</style>",
        "</head>",
        "<body>",
        '<div class="controls">',
        '  <div class="size-select">',
        "    <strong>Select Image Size: </strong>",
        '    <select id="sizeSelector" onchange="changeSize()">',
        '      <option value="gallery-small">Small</option>',
        '      <option value="gallery-medium" selected>Medium</option>',
        '      <option value="gallery-large">Large</option>',
        "    </select>",
        "  </div>",
        '  <div class="toggle" onclick="toggleDarkMode()">Toggle Dark Mode</div>',
        "</div>",
        f"<h1>Gallery – Page {page_num} of {total_pages}</h1>",
        '<div class="search-bar">',
        '    <input type="text" id="searchBox" '
        'placeholder="Search by title..." oninput="filterGallery()">',
        "</div>",
        '<div class="gallery-grid gallery-medium" id="gallery">',
    ]

    for item in page_items:
        created = datetime.utcfromtimestamp(item.get("created_at", 0)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        title = item.get("title") or ""
        data_title = title.lower()
        tags = ", ".join(item.get("tags", [])) or "—"
        html.extend(
            [
                f'<div class="image-card" data-title="{data_title}">',
                f"  <a href=\"{item['image_path']}\" target=\"_blank\">",
                f"    <img src=\"{item['image_path']}\" alt=\"{title}\">",
                "  </a>",
                '  <div class="meta">',
                f"    <strong>{title or item['id']}</strong><br>",
                f"    {created}<br>",
                f"    Tags: {tags}<br>",
                f"    <a href=\"{item.get('conversation_link', '#')}\" "
                f'target="_blank">View conversation</a>',
                "  </div>",
                "</div>",
            ]
        )

    html.append("</div><div style='text-align:center;margin-top:30px;'>")
    if page_num > 1:
        html.append(f'<a href="page_{page_num - 1}.html">&laquo; Prev</a> ')
    if page_num < total_pages:
        html.append(f'<a href="page_{page_num + 1}.html">Next &raquo;</a>')
    html.extend(
        [
            "</div>",
            "<script>",
            "function toggleDarkMode() {",
            "    document.body.classList.toggle('dark');",
            "    localStorage.setItem('theme', "
            "document.body.classList.contains('dark') ? 'dark' : 'light');",
            "}",
            "if (localStorage.getItem('theme') === 'dark') {",
            "    document.body.classList.add('dark');",
            "}",
            "function filterGallery() {",
            "    const input = document.getElementById('searchBox').value."
            "toLowerCase();",
            "    const cards = document.querySelectorAll('.image-card');",
            "    cards.forEach(card => {",
            "        const title = card.dataset.title;",
            "        card.style.display = title.includes(input) ? '' : 'none';",
            "    });",
            "}",
            "function changeSize() {",
            "    const gallery = document.getElementById('gallery');",
            "    gallery.className = 'gallery-grid ' + "
            "document.getElementById('sizeSelector').value;",
            "}",
            "</script>",
            "</body></html>",
        ]
    )
    return "\n".join(html)


def _generate_index(num_pages: int) -> str:
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        "<title>Image Gallery Index</title>",
        "<style>body { font-family: sans-serif; margin: 30px; } "
        "a { text-decoration: none; }</style>",
        "</head>",
        "<body>",
        "<h1>Image Gallery</h1>",
        "<ul>",
    ]
    for i in range(1, num_pages + 1):
        lines.append(f'<li><a href="page_{i}.html">Page {i}</a></li>')
    lines.extend(["</ul>", "</body></html>"])
    return "\n".join(lines)


def generate_gallery(gallery_root: str = "gallery", images_per_page: int = 500) -> int:
    os.makedirs(gallery_root, exist_ok=True)
    items = _load_all_metadata(gallery_root)
    if not items:
        return 0

    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    pages = [
        items[i : i + images_per_page] for i in range(0, len(items), images_per_page)
    ]

    for idx, page in enumerate(pages, 1):
        html = _generate_html(page, idx, len(pages))
        with open(
            os.path.join(gallery_root, f"page_{idx}.html"),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(html)

    index_html = _generate_index(len(pages))
    with open(os.path.join(gallery_root, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    return len(items)


if __name__ == "__main__":
    total = generate_gallery()
    if total:
        print(f"Generated gallery with {total} images.")
    else:
        print("No gallery generated (no images found).")
