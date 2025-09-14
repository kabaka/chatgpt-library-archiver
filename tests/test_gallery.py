import json
from pathlib import Path

from chatgpt_library_archiver.gallery import generate_gallery


def write_metadata(root: Path, version: str, items):
    vdir = root / version
    (vdir / "images").mkdir(parents=True, exist_ok=True)
    with open(vdir / f"metadata_{version}.json", "w", encoding="utf-8") as f:
        json.dump(items, f)


def test_generate_gallery_includes_new_versions(tmp_path):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    # initial version with one image
    write_metadata(
        gallery_root, "v1", [{"id": "1", "filename": "a.jpg", "created_at": 1}]
    )
    (gallery_root / "v1" / "images" / "a.jpg").write_text("img")

    generate_gallery(str(gallery_root), images_per_page=1)
    html = (gallery_root / "page_1.html").read_text()
    assert "v1/images/a.jpg" in html

    # add new version and regenerate
    write_metadata(
        gallery_root, "v2", [{"id": "2", "filename": "b.jpg", "created_at": 2}]
    )
    (gallery_root / "v2" / "images" / "b.jpg").write_text("img")

    generate_gallery(str(gallery_root), images_per_page=1)
    html = (gallery_root / "page_1.html").read_text()
    assert "v2/images/b.jpg" in html
    # old image should still appear (likely on page_2 due to images_per_page=1)
    html2 = (gallery_root / "page_2.html").read_text()
    assert "v1/images/a.jpg" in html2
