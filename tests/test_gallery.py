import json
import re
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


def test_viewer_image_css_preserves_aspect_ratio():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    match = re.search(r"#viewer img \{[^}]*\}", html)
    assert match, "viewer img block not found"
    block = match.group(0)
    assert "width: auto" in block
    assert "height: auto" in block


def test_gallery_prefers_color_scheme():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "@media (prefers-color-scheme: dark)" in html


def test_gallery_hides_metadata_until_hover():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert ".meta {" in html and "display: none" in html
    assert ".image-card:hover .meta" in html


def test_gallery_limits_metadata_height_and_truncates_tags():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    meta_block = re.search(r"\.meta \{[^}]*\}", html)
    assert meta_block and "max-height: 50%" in meta_block.group(0)
    tags_block = re.search(r"\.meta \.tags \{[^}]*\}", html)
    assert tags_block and "font-size: 0.7em" in tags_block.group(0)
    assert "text-overflow: ellipsis" in tags_block.group(0)
    assert "tagsArr.slice(0, 5)" in html


def test_gallery_uses_css_variables_and_layout():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert '<div class="layout">' in html
    assert ":root {" in html
    assert "--thumb-size" in html


def test_gallery_has_sticky_header():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert '<header class="top-bar">' in html
    assert "position: sticky" in html


def test_gallery_grid_centers_images_and_is_full_width():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "grid-auto-rows" in html
    img_block = re.search(r"\.image-card img \{[^}]*\}", html)
    assert img_block and "object-fit: contain" in img_block.group(0)
    header_block = re.search(r"header.top-bar \{[^}]*\}", html)
    assert header_block and "width: 100%" in header_block.group(0)


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
    assert '<div class="layout">' in expected

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


def _extract_viewer_script() -> str:
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    start = html.index("let viewerData")
    end = html.index("loadImages();")
    return html[start:end]


def _extract_thumb_handler() -> str:
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    start = html.index("const link = card.querySelector('a.thumb');")
    start = html.index("link.addEventListener", start)
    end = html.index("const img = card.querySelector('img');", start)
    snippet = html[start:end]
    return "function attach(link, openViewer, index) {\n" + snippet + "}\n"


def test_filter_by_date_range():
    fn = _extract_filter_fn()
    script = (
        "function updateVisibleIndices(){}\n"
        + fn
        + textwrap.dedent(
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
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ",none"


def test_filter_by_tags_boolean():
    fn = _extract_filter_fn()
    script = (
        "function updateVisibleIndices(){}\n"
        + fn
        + textwrap.dedent(
            """
        const inputs = {
          searchBox: { value: 'cat AND (black OR white)' },
          startDate: { value: '' },
          endDate: { value: '' },
        };
        const cards = [
          { dataset: { title: 'img1', tags: 'blackcat\\npet' }, style: {} },
          { dataset: { title: 'img2', tags: 'whitecat\\npet' }, style: {} },
          { dataset: { title: 'img3', tags: 'graycat\\npet' }, style: {} },
        ];
        const document = {
          getElementById: id => inputs[id],
          querySelectorAll: () => cards,
        };
        filterGallery();
        console.log(cards.map(c => c.style.display).join(','));
        """
        )
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ",,none"


def test_viewer_keyboard_navigation():
    script = textwrap.dedent(
        """
        const elements = {
          viewer: { style: { display: 'none' } },
          viewerImg: { src: '', alt: '' },
          viewerRaw: { href: '' },
        };
        const cards = [
          { dataset: { index: '0' }, style: { display: '' } },
          { dataset: { index: '1' }, style: { display: '' } },
        ];
        const document = {
          getElementById: id => elements[id],
          querySelectorAll: () => cards,
          addEventListener: (type, handler) => { document._handler = handler; },
        };
        """
    )
    script += _extract_viewer_script()
    script += textwrap.dedent(
        """
        viewerData = [{src: 'a.jpg', title: 'a'}, {src: 'b.jpg', title: 'b'}];
        openViewer(0);
        document._handler({ key: 'ArrowRight' });
        console.log(
          elements.viewerImg.src + ',' +
          elements.viewerRaw.href + ',' +
          elements.viewer.style.display
        );
        document._handler({ key: 'ArrowLeft' });
        console.log(elements.viewerImg.src);
        document._handler({ key: 'Escape' });
        console.log(elements.viewer.style.display);
        """
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip().splitlines() == ["b.jpg,b.jpg,flex", "a.jpg", "none"]


def test_viewer_navigation_respects_filters():
    script = textwrap.dedent(
        """
        const elements = {
          viewer: { style: { display: 'none' } },
          viewerImg: { src: '', alt: '' },
          viewerRaw: { href: '' },
        };
        const cards = [
          { dataset: { index: '0' }, style: { display: '' } },
          { dataset: { index: '1' }, style: { display: 'none' } },
          { dataset: { index: '2' }, style: { display: '' } },
        ];
        const document = {
          getElementById: id => elements[id],
          querySelectorAll: () => cards,
          addEventListener: (type, handler) => { document._handler = handler; },
        };
        """
    )
    script += _extract_viewer_script()
    script += textwrap.dedent(
        """
        viewerData = [
          {src: 'a.jpg', title: 'a'},
          {src: 'b.jpg', title: 'b'},
          {src: 'c.jpg', title: 'c'},
        ];
        openViewer(0);
        document._handler({ key: 'ArrowRight' });
        console.log(elements.viewerImg.src);
        """
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "c.jpg"


def test_ctrl_meta_click_opens_raw():
    handler = _extract_thumb_handler()
    script = handler + textwrap.dedent(
        """
        let opened = null;
        function openViewer(i){ opened = i; }
        const link = { addEventListener: (evt, fn) => { link.handler = fn; } };
        attach(link, openViewer, 42);
        const ctrlEvent = {
          ctrlKey: true,
          metaKey: false,
          preventDefault: () => { ctrlEvent.prevented = true; },
        };
        link.handler(ctrlEvent);
        const metaEvent = {
          ctrlKey: false,
          metaKey: true,
          preventDefault: () => { metaEvent.prevented = true; },
        };
        link.handler(metaEvent);
        const normalEvent = {
          ctrlKey: false,
          metaKey: false,
          preventDefault: () => { normalEvent.prevented = true; },
        };
        link.handler(normalEvent);
        console.log(JSON.stringify({
          ctrlPrevented: ctrlEvent.prevented || false,
          metaPrevented: metaEvent.prevented || false,
          normalPrevented: normalEvent.prevented || false,
          opened
        }));
        """
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    data = json.loads(result.stdout)
    assert data == {
        "ctrlPrevented": False,
        "metaPrevented": False,
        "normalPrevented": True,
        "opened": 42,
    }
