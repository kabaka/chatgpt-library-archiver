import json
import re
import subprocess
import textwrap
from importlib import resources

from chatgpt_library_archiver.gallery import generate_gallery


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


def test_gallery_has_csp_meta_tag():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'self'" in html
    assert "script-src 'unsafe-inline'" in html
    assert "style-src 'unsafe-inline'" in html
    assert "img-src 'self' data:" in html


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


def test_small_gallery_hides_date_and_tags():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "createdSpan.className = 'created'" in html
    assert "tagsSpan.className = 'tags'" in html
    css = re.search(
        r"\.gallery-small \.meta \.created,\s*\.gallery-small \.meta \.tags \{[^}]*\}",
        html,
    )
    assert css and "display: none" in css.group(0)


def test_gallery_limits_metadata_height_and_truncates_tags():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    meta_block = re.search(r"\.meta \{[^}]*\}", html)
    assert meta_block and "max-height: 50%" in meta_block.group(0)
    assert ".tag-pill" in html
    assert "tagsArr.slice(0, 5)" in html


def test_gallery_uses_css_variables_and_layout():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert '<main class="layout">' in html
    assert ":root {" in html
    assert "--thumb-size" in html


def test_gallery_has_sticky_header():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert '<header class="top-bar">' in html
    assert "position: sticky" in html


def test_gallery_has_reset_and_github_link():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert 'id="resetFilters"' in html
    assert "Date range:" in html
    assert 'href="https://github.com/kabaka/chatgpt-library-archiver"' in html


def test_gallery_has_search_help_tooltip():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert 'placeholder="Search images"' in html
    assert 'id="searchHelp"' in html
    assert "Use AND, OR, NOT, and parentheses to refine search" in html


def test_gallery_has_full_size_mode_with_preload_and_swipe():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert 'option value="gallery-full"' in html
    assert ".gallery-full {" in html
    assert "setAttribute('data-thumb-full'" in html
    assert "rootMargin: '200px 0px'" in html
    assert "viewerEl.addEventListener('touchend'" in html
    assert "viewerEl.addEventListener('click'" in html


def test_gallery_grid_centers_images_and_is_full_width():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "grid-auto-rows" in html
    img_block = re.search(r"\.image-card img \{[^}]*\}", html)
    assert img_block and "object-fit: contain" in img_block.group(0)
    header_block = re.search(r"header.top-bar \{[^}]*\}", html)
    assert header_block and "width: 100%" in header_block.group(0)


def test_gallery_uses_border_box_sizing():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "*, *::before, *::after {" in html
    assert "box-sizing: border-box" in html


def test_gallery_persists_theme_size_and_filter():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "sessionStorage.setItem('size'" in html
    assert "sessionStorage.getItem('size')" in html
    assert "sessionStorage.setItem('theme'" in html
    assert "sessionStorage.getItem('theme')" in html
    assert "sessionStorage.setItem('filter-text'" in html
    assert "sessionStorage.getItem('filter-text')" in html


def test_generate_gallery_creates_single_index(tmp_path, write_metadata):
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
    assert "img.loading = 'lazy'" in expected
    assert "setAttribute('data-src'" in expected
    assert "setAttribute('data-full'" in expected
    assert '<main class="layout">' in expected

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


def test_generate_gallery_handles_empty_metadata(tmp_path, write_metadata):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    write_metadata(gallery_root, [])

    total = generate_gallery(str(gallery_root))

    assert total == 0
    assert not (gallery_root / "index.html").exists()


def test_generate_gallery_backfills_missing_created_at(tmp_path, write_metadata):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    write_metadata(
        gallery_root,
        [
            {
                "id": "missing",
                "filename": "a.jpg",
                "created_at": None,
            }
        ],
    )

    images_dir = gallery_root / "images"
    (images_dir / "a.jpg").write_text("img")

    total = generate_gallery(str(gallery_root))

    assert total == 1
    with open(gallery_root / "metadata.json", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["created_at"] == 0.0


def test_generate_gallery_handles_mixed_created_at_types(tmp_path, write_metadata):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    write_metadata(
        gallery_root,
        [
            {
                "id": "invalid",
                "filename": "c.jpg",
                "created_at": "not-a-date",
            },
            {"id": "old", "filename": "b.jpg", "created_at": 1},
            {
                "id": "recent",
                "filename": "a.jpg",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ],
    )
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        (gallery_root / "images" / name).write_text("img")

    generate_gallery(str(gallery_root))

    with open(gallery_root / "metadata.json", encoding="utf-8") as f:
        sorted_data = json.load(f)

    assert [item["id"] for item in sorted_data] == ["recent", "old", "invalid"]
    assert all(isinstance(item["created_at"], float) for item in sorted_data)


def _extract_search_fn() -> str:
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    start = html.index("function tokenize(expr)")
    end = html.index("/* === Sorting === */")
    return html[start:end]


def _extract_viewer_script() -> str:
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    fn_start = html.index("function showViewerAt(pos)")
    fn_end = html.index("/* === Initialization === */")
    kb_start = html.index("// Keyboard navigation")
    kb_end = html.index("// Viewer click/touch handlers")
    return html[fn_start:fn_end] + html[kb_start:kb_end]


def _extract_thumb_handler() -> str:
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    start = html.index("link.addEventListener('click'")
    end = html.index("return { card: card, img: img };", start)
    snippet = html[start:end]
    return "function attach(link, openViewer, filteredIndex) {\n" + snippet + "}\n"


def test_filter_by_date_range():
    fn = _extract_search_fn()
    script = fn + textwrap.dedent(
        """
        var startMs = new Date('1970-01-02').getTime();
        var endMs = new Date('1970-01-02').getTime();
        var items = [
          { _searchTitle: 'a', _searchTags: '', created_at: startMs / 1000 },
          { _searchTitle: 'b', _searchTags: '',
            created_at: (startMs + 86400000) / 1000 },
        ];
        var searchFn = function() { return true; };
        var filtered = items.filter(function(item) {
          var created = item.created_at ? item.created_at * 1000 : null;
          if (startMs !== null && (!created || created < startMs)) return false;
          if (endMs !== null && (!created || created > endMs)) return false;
          return true;
        });
        console.log(filtered.map(function(i) { return i._searchTitle; }).join(','));
        """
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "a"


def test_filter_by_tags_boolean():
    fn = _extract_search_fn()
    script = fn + textwrap.dedent(
        """
        var items = [
          { _searchTitle: 'img1', _searchTags: 'blackcat\\npet' },
          { _searchTitle: 'img2', _searchTags: 'whitecat\\npet' },
          { _searchTitle: 'img3', _searchTags: 'graycat\\npet' },
        ];
        var searchFn = makeSearchFn('cat AND (black OR white)');
        var filtered = items.filter(function(item) { return searchFn(item); });
        console.log(filtered.map(function(i) { return i._searchTitle; }).join(','));
        """
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "img1,img2"


def test_viewer_keyboard_navigation():
    script = textwrap.dedent(
        """
        const elements = {
          viewer: {
            style: { display: 'none' },
            addEventListener: () => {},
            focus: () => {},
            querySelectorAll: () => [],
          },
          viewerImg: { src: '', alt: '' },
          viewerRaw: { href: '' },
        };
        const document = {
          getElementById: id => elements[id],
          querySelector: () => null,
          addEventListener: (type, handler) => {
            document._handler = handler;
          },
          activeElement: null,
        };
        var visibleIndices = [0, 1];
        var currentIndex = 0;
        var viewerTrigger = null;
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
          viewer: {
            style: { display: 'none' },
            addEventListener: () => {},
            focus: () => {},
            querySelectorAll: () => [],
          },
          viewerImg: { src: '', alt: '' },
          viewerRaw: { href: '' },
        };
        const document = {
          getElementById: id => elements[id],
          querySelector: () => null,
          addEventListener: (type, handler) => {
            document._handler = handler;
          },
          activeElement: null,
        };
        var visibleIndices = [0, 2];
        var currentIndex = 0;
        var viewerTrigger = null;
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
