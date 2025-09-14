import json
from pathlib import Path

from chatgpt_library_archiver.gallery import generate_gallery


def write_metadata(root: Path, items):
    (root / "images").mkdir(parents=True, exist_ok=True)
    with open(root / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(items, f)


def test_generate_gallery_includes_all_images(tmp_path):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    # initial image
    write_metadata(gallery_root, [{"id": "1", "filename": "a.jpg", "created_at": 1}])
    (gallery_root / "images" / "a.jpg").write_text("img")

    generate_gallery(str(gallery_root), images_per_page=1)
    html = (gallery_root / "page_1.html").read_text()
    assert "images/a.jpg" in html

    # add second image and regenerate
    with open(gallery_root / "metadata.json", encoding="utf-8") as f:
        data = json.load(f)
    data.append({"id": "2", "filename": "b.jpg", "created_at": 2})
    with open(gallery_root / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(data, f)
    (gallery_root / "images" / "b.jpg").write_text("img")

    generate_gallery(str(gallery_root), images_per_page=1)
    html = (gallery_root / "page_1.html").read_text()
    assert "images/b.jpg" in html
    # old image should still appear on second page
    html2 = (gallery_root / "page_2.html").read_text()
    assert "images/a.jpg" in html2


def test_consolidates_legacy_metadata(tmp_path):
    gallery_root = tmp_path / "gallery"
    legacy = gallery_root / "v1"
    (legacy / "images").mkdir(parents=True)

    meta = [{"id": "1", "filename": "a.jpg", "created_at": 1}]
    with open(legacy / "metadata_v1.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)
    (legacy / "images" / "a.jpg").write_text("img")

    generate_gallery(str(gallery_root), images_per_page=1)

    assert not legacy.exists()
    assert (gallery_root / "images" / "a.jpg").exists()
    data = json.loads((gallery_root / "metadata.json").read_text())
    assert data[0]["id"] == "1"
    html = (gallery_root / "page_1.html").read_text()
    assert "images/a.jpg" in html
