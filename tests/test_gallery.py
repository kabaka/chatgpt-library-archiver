import json
from importlib import resources
from pathlib import Path

from chatgpt_library_archiver.gallery import generate_gallery


def write_metadata(root: Path, items):
    (root / "images").mkdir(parents=True, exist_ok=True)
    with open(root / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(items, f)


def test_gallery_template_packaged():
    assert resources.is_resource("chatgpt_library_archiver", "gallery_index.html")


def test_generate_gallery_creates_single_index(tmp_path):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    write_metadata(gallery_root, [{"id": "1", "filename": "a.jpg", "created_at": 1}])
    (gallery_root / "images" / "a.jpg").write_text("img")

    generate_gallery(str(gallery_root))
    index = gallery_root / "index.html"
    assert index.exists()
    assert not any(gallery_root.glob("page_*.html"))
    expected = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert index.read_text() == expected

    with open(gallery_root / "metadata.json", encoding="utf-8") as f:
        data = json.load(f)
    data.append({"id": "2", "filename": "b.jpg", "created_at": 2})
    with open(gallery_root / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(data, f)
    (gallery_root / "images" / "b.jpg").write_text("img")

    generate_gallery(str(gallery_root))
    with open(gallery_root / "metadata.json", encoding="utf-8") as f:
        sorted_data = json.load(f)
    assert [item["id"] for item in sorted_data] == ["2", "1"]
