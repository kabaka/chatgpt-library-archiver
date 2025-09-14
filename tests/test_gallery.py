import json
import subprocess
import textwrap
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
    assert 'loading="lazy"' in expected
    assert "data-src" in expected

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


def _extract_filter_fn() -> str:
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    start = html.index("function filterGallery")
    end = html.index("function changeSize")
    return html[start:end]


def test_filter_by_date_range():
    fn = _extract_filter_fn()
    script = fn + textwrap.dedent(
        """
        const startMs = new Date('1970-01-02').getTime();
        const inputs = {
          searchBox: { value: '' },
          startDate: { value: '1970-01-02' },
          endDate: { value: '1970-01-02' },
        };
        const later = startMs + 86400000;
        const cards = [
          {
            dataset: { title: 'a', created: String(startMs) },
            style: {},
          },
          {
            dataset: { title: 'b', created: String(later) },
            style: {},
          },
        ];
        const document = {
          getElementById: id => inputs[id],
          querySelectorAll: () => cards,
        };
        filterGallery();
        console.log(cards.map(c => c.style.display).join(','));
        """
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ",none"
