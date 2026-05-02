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
    assert "default-src 'none'" in html
    assert "script-src 'unsafe-inline'" in html
    assert "style-src 'unsafe-inline'" in html
    assert "img-src * data:" in html


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
    # Swipe handling now lives in the pointerup branch.
    assert "viewerEl.addEventListener('pointerup'" in html
    assert "viewerEl.addEventListener('click'" in html


def test_gallery_full_mode_serves_original_image():
    """Task 3 regression: in `gallery-full` list mode, the rendered <img>
    must resolve to the ORIGINAL image (`images/<filename>`), not a 400px
    `large` thumbnail. See docs/reviews/2026-05-01-feature-batch/PLAN.md.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )

    # The size-key → width hint must advertise a high-DPI width for `full`
    # so the browser picks the original from `srcset`. The legacy 400px
    # mapping was the bug.
    assert re.search(
        r"sizeKeyToWidth\s*=\s*\{\s*small:\s*150,\s*medium:\s*250,"
        r"\s*large:\s*400,\s*full:\s*2400\s*\}",
        html,
    ), "sizeKeyToWidth.full must be 2400 (originals tier), not 400"
    # Hard regression sentinel: the old `full: 400` mapping must be gone.
    assert "full: 400" not in html, (
        "Legacy low-res `full: 400` mapping resurfaced — "
        "Task 3 (full-resolution gallery-full) regressed."
    )

    # `srcset` for full mode appends the original at 2400w. The two call
    # sites are `createCard` (initial render) and `updateThumbnailsForSize`
    # (size selector change). Both must include the `2400w` descriptor and
    # gate it on `sizeKey === 'full'`.
    assert "srcsetForKey" in html, (
        "srcsetForKey helper missing — full-mode srcset will not include "
        "the original image."
    )
    assert "' 2400w'" in html or "+ ' 2400w'" in html, (
        "Original-image descriptor `2400w` not found in srcset assembly."
    )
    assert "sizeKey === 'full'" in html, (
        "Full-mode srcset gating missing; smaller modes would also pull "
        "the original and waste bandwidth."
    )

    # In `updateThumbnailsForSize`, full mode must explicitly point
    # `nextSrc` at `data-full` (the original) rather than relying on the
    # `data-thumb-full` cascade.
    assert "img.dataset.full" in html
    update_block = re.search(
        r"function updateThumbnailsForSize\(sizeKey\) \{.*?\n\}",
        html,
        re.DOTALL,
    )
    assert update_block, "updateThumbnailsForSize body not found"
    body = update_block.group(0)
    assert "sizeKey === 'full'" in body, (
        "updateThumbnailsForSize must branch on full mode to swap to the "
        "original image."
    )
    assert "img.dataset.full" in body


def test_gallery_small_modes_use_thumbnail_tiers():
    """Smaller list modes (small/medium/large) must keep using the
    existing 150/250/400 thumbnail tiers and must NOT eagerly download
    the original image via `srcset`.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    # Width hints for the small tiers are unchanged.
    assert "small: 150" in html
    assert "medium: 250" in html
    assert "large: 400" in html
    # The 2400w descriptor must be guarded by a `full` check; a global
    # (unconditional) inclusion would push originals into grid mode too.
    assert re.search(
        r"sizeKey === 'full'[^\n]*\n[^\n]*' 2400w'|"
        r"sizeKey === 'full'\)\s*\{[^}]*' 2400w'",
        html,
        re.DOTALL,
    ), "2400w original-image descriptor must be gated on full mode"


def test_viewer_uses_pointer_events_for_close():
    """Pinch-to-close regression: viewer must close via pointer events,
    not raw touchstart/touchend, and pinch (multi-touch) must not close.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    # New pointer-event handlers exist on the viewer.
    assert "viewerEl.addEventListener('pointerdown'" in html
    assert "viewerEl.addEventListener('pointerup'" in html
    assert "viewerEl.addEventListener('pointercancel'" in html
    # Pointer-count tracking sentinel (used to suppress close on pinch).
    assert "activePointers" in html
    assert "wasMultiTouch" in html
    # Regression check: the legacy touchstart/touchend viewer listeners
    # are gone. Pinch's second-finger touchend used to fall through to
    # closeViewer() — see Task 4 of docs/reviews/2026-05-01-feature-batch.
    assert "viewerEl.addEventListener('touchstart'" not in html
    assert "viewerEl.addEventListener('touchend'" not in html


def test_viewer_image_has_touch_action_manipulation():
    """`touch-action: manipulation` keeps native pinch-zoom + pan-after-zoom
    enabled while suppressing the synthetic 300ms click delay. The literal
    `pinch-zoom` value would disable pan-x/pan-y and is intentionally not used.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    viewer_img_block = re.search(r"#viewer img \{[^}]*\}", html)
    assert viewer_img_block, "#viewer img CSS block not found"
    assert "touch-action: manipulation" in viewer_img_block.group(0)


def test_gallery_disables_hover_overlay_on_touch_devices():
    """Task 5: on (hover: none) and (pointer: coarse) the :hover/:focus-within
    overlay must be disabled — browsers synthesize :hover on first tap, so any
    scroll-touch that grazes a card pops the panel.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    block = re.search(
        r"@media \(hover: none\) and \(pointer: coarse\)\s*\{[^{}]*"
        r"\.image-card:hover \.meta[^{}]*\.image-card:focus-within \.meta[^{}]*"
        r"\{[^{}]*display:\s*none[^{}]*\}\s*\}",
        html,
        re.DOTALL,
    )
    assert block, (
        "expected an @media (hover: none) and (pointer: coarse) block that "
        "disables .image-card:hover/.focus-within .meta"
    )


def test_gallery_long_press_handler_registered():
    """Task 5: long-press detection (~500ms hold without movement) on cards
    must be wired up via pointerdown on the gallery container.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "longPressTimer" in html
    assert "LONG_PRESS_MS" in html
    assert "500" in html  # the long-press threshold
    assert "galleryEl.addEventListener('pointerdown'" in html
    # Movement threshold cancels the timer (scroll-as-long-press guard).
    assert "LONG_PRESS_MOVE" in html
    assert "clearLongPress" in html
    # Coarse-pointer gating: handler is a no-op on hover-capable devices.
    assert "(hover: none) and (pointer: coarse)" in html
    assert "matchMedia" in html


def test_gallery_metadata_modal_markup_exists():
    """Task 5: the long-press modal must exist in the template with the
    expected accessibility attributes and is hidden by default.
    """
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    modal = re.search(r'<div id="metaModal"[^>]*>', html)
    assert modal, "metaModal element missing"
    attrs = modal.group(0)
    assert 'role="dialog"' in attrs
    assert 'aria-modal="true"' in attrs
    assert 'tabindex="-1"' in attrs
    # Hidden by default.
    assert 'data-open="false"' in attrs
    # Required inner fields.
    assert 'id="metaModalTitle"' in html
    assert 'id="metaModalPrompt"' in html
    assert 'id="metaModalTags"' in html
    assert 'id="metaModalClose"' in html


def test_gallery_metadata_modal_dismisses_on_escape_and_backdrop():
    """Task 5: the metadata modal must close on Escape and on backdrop click."""
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    # Escape closes when modal is open.
    escape_block = re.search(
        r"e\.key === 'Escape'[^\n]*isMetaModalOpen\(\)[^\n]*",
        html,
    )
    assert escape_block, "Escape-to-close handler for metaModal not found"
    # Backdrop click (target === metaModal) closes.
    backdrop_block = re.search(
        r"metaModal\.addEventListener\('click'[^}]*?e\.target === metaModal"
        r"[^}]*?closeMetaModal\(\)",
        html,
        re.DOTALL,
    )
    assert backdrop_block, "Backdrop-tap close handler for metaModal not found"


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
    html = index.read_text(encoding="utf-8")
    # Metadata is embedded as a GALLERY_DATA variable in the HTML head
    assert "<script>var GALLERY_DATA = [" in html
    assert ";</script>\n</head>" in html
    # Template structure is preserved
    assert "img.loading = 'lazy'" in html
    assert "setAttribute('data-src'" in html
    assert "setAttribute('data-full'" in html
    assert '<main class="layout">' in html

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


# -- XSS security tests for embedded metadata JSON --


def test_safe_json_for_html_escapes_dangerous_sequences():
    """Unit test: _safe_json_for_html escapes <, >, and & in serialized JSON."""
    from chatgpt_library_archiver.gallery import _safe_json_for_html
    from chatgpt_library_archiver.metadata import GalleryItem

    items = [
        GalleryItem(
            id="xss-1",
            filename="evil.png",
            title='</script><script>alert("xss")</script>',
            tags=["<script>", "<!--", "tag&amp;"],
            prompt='<img onerror="alert(1)">',
            created_at=1.0,
        ),
    ]

    result = _safe_json_for_html(items)

    # No raw angle brackets or ampersands in the output
    assert "</script>" not in result
    assert "<script>" not in result
    assert "<!--" not in result
    assert "&amp;" not in result
    assert "<" not in result
    assert ">" not in result
    assert "&" not in result

    # The escaped sequences ARE present
    assert "\\u003c" in result
    assert "\\u003e" in result
    assert "\\u0026" in result

    # Round-trip: the JSON can be parsed back and recovers original data
    recovered = json.loads(result)
    assert len(recovered) == 1
    assert recovered[0]["title"] == '</script><script>alert("xss")</script>'
    assert recovered[0]["tags"] == ["<script>", "<!--", "tag&amp;"]
    assert recovered[0]["prompt"] == '<img onerror="alert(1)">'


def test_generate_gallery_xss_payloads_escaped_in_html(tmp_path, write_metadata):
    """Integration test: XSS payloads in metadata are escaped in generated HTML."""
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()

    xss_payloads = {
        "id": "xss-int",
        "filename": "payload.jpg",
        "title": '</script><script>alert("xss")</script>',
        "tags": ["<script>", "<!--", "&amp;injection"],
        "prompt": '<img src=x onerror="alert(document.cookie)">',
        "created_at": 1.0,
    }
    write_metadata(gallery_root, [xss_payloads])
    (gallery_root / "images" / "payload.jpg").write_text("img")

    generate_gallery(str(gallery_root))

    html = (gallery_root / "index.html").read_text(encoding="utf-8")

    # Extract the embedded JSON from the script block
    marker_start = "<script>var GALLERY_DATA = "
    marker_end = ";</script>"
    start_idx = html.index(marker_start) + len(marker_start)
    end_idx = html.index(marker_end, start_idx)
    embedded_json_str = html[start_idx:end_idx]

    # None of the dangerous raw sequences appear in the embedded JSON
    assert "</script>" not in embedded_json_str
    assert "<script>" not in embedded_json_str
    assert "<!--" not in embedded_json_str
    assert "&amp;" not in embedded_json_str

    # The JSON is valid and round-trips to recover the original payloads
    recovered = json.loads(embedded_json_str)
    assert len(recovered) == 1
    item = recovered[0]
    assert item["title"] == '</script><script>alert("xss")</script>'
    assert item["tags"] == ["<script>", "<!--", "&amp;injection"]
    assert item["prompt"] == '<img src=x onerror="alert(document.cookie)">'


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
    kb_end = html.index("// Viewer pointer/click handlers")
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
          viewerImg: { src: '', alt: '', style: { opacity: '' }, onload: null },
          viewerRaw: { href: '' },
          viewerCounter: { textContent: '' },
          viewerSpinner: { style: { display: '' } },
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
          viewerImg: { src: '', alt: '', style: { opacity: '' }, onload: null },
          viewerRaw: { href: '' },
          viewerCounter: { textContent: '' },
          viewerSpinner: { style: { display: '' } },
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


# -- Task 7: tag affinity sort tests --


def test_affinity_index_present_in_sort_dropdown():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert '<option value="affinity">Tag similarity</option>' in html


def test_affinity_index_referenced_in_js_comparator():
    html = resources.read_text(
        "chatgpt_library_archiver", "gallery_index.html", encoding="utf-8"
    )
    assert "case 'affinity':" in html
    assert "a.affinity_index" in html
    assert "b.affinity_index" in html


def test_generate_gallery_writes_affinity_index(tmp_path, write_metadata):
    gallery_root = tmp_path / "gallery"
    gallery_root.mkdir()
    write_metadata(
        gallery_root,
        [
            {"id": "1", "filename": "a.jpg", "created_at": 1, "tags": ["x", "y"]},
            {"id": "2", "filename": "b.jpg", "created_at": 2, "tags": ["x", "y"]},
            {"id": "3", "filename": "c.jpg", "created_at": 3, "tags": []},
            {"id": "4", "filename": "d.jpg", "created_at": 4, "tags": ["x"]},
        ],
        create_images=True,
    )
    generate_gallery(str(gallery_root))
    with open(gallery_root / "metadata.json", encoding="utf-8") as f:
        data = json.load(f)
    by_id = {row["id"]: row for row in data}
    assert by_id["3"]["affinity_index"] is None
    assert by_id["1"]["affinity_index"] is not None
    assert by_id["2"]["affinity_index"] is not None
    assert by_id["4"]["affinity_index"] is not None
    # Items 1 and 2 share both tags; they should be adjacent in the sequence.
    indices = sorted((by_id[i]["affinity_index"], i) for i in ("1", "2", "4"))
    assert {indices[0][1], indices[1][1]} == {"1", "2"}
