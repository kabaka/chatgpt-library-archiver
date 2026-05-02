# Feature Batch Implementation Plan — 2026-05-01

This plan covers seven coordinated changes to chatgpt-library-archiver: a new
gallery management subcommand suite, a tag-merge bug fix, two lightbox/mobile
UX fixes, a full-resolution lightbox upgrade, parallelized thumbnail
generation, and a tag-similarity sort mode. All file paths are workspace
relative.

## Executive Summary

1. Add a `gallery` subcommand group (rename existing `gallery` → `gallery build`) with `query`, `tag`, `untag`, `set`, `unset`, `mv`, `rm`, `stats`, and `affinity` subcommands.
2. Fix the tag-merge bug in [tagger.py](src/chatgpt_library_archiver/tagger.py#L219) — replace `item.tags = tags` with an order-preserving dedupe merge of existing + AI tags. Affects both `import --tag ... --tag-new` and `download --tag-new`.
3. **Full-resolution images in `gallery-full` list mode** — the lightbox already serves the original; the bug lives in the `gallery-full` size-key path. Fix `srcset`/`sizes` plumbing in [gallery_index.html](src/chatgpt_library_archiver/gallery_index.html#L582). Introduce no new thumbnail tier (justified below).
4. Fix pinch-to-close bug by switching the viewer to Pointer Events and only treating a single-pointer tap (no movement, no second finger ever pressed) as close.
5. Replace the `:hover` overlay on touch devices with a long-press (≥500 ms) full-screen modal; tap = open viewer; scroll = no overlay; gated by `(hover: none) and (pointer: coarse)`.
6. Parallelize the import / download per-image thumbnail generation by introducing a `create_thumbnails_batch()` that uses the existing `_create_thumbnails_worker` + `ProcessPoolExecutor` plumbing.
7. Add tag-affinity sort: precompute an `affinity_index` on each item via a Jaccard-greedy nearest-neighbor traversal seeded by the largest tag cluster, written into `metadata.json` during `gallery build`.
8. Three ADRs recommended: tag affinity sort, full-resolution lightbox decision, gallery management CLI shape.
9. Recommended order: bug fixes (#2, #4) → thumbnail parallelization (#6) → lightbox full-res (#3) → mobile hover modal (#5) → affinity sort (#7) → management CLI (#1, depends on #7 metadata field).
10. Highest-risk task is #5 (touch UX); highest-value, lowest-risk is #2 (tag merge fix).

---

## Task 1 — Gallery Management Subcommands

### Scope

Currently, `chatgpt-library-archiver gallery` rebuilds the static viewer.
There is no first-class CLI for inspecting or mutating the existing gallery
beyond the `tag` subcommand. We introduce a richer set of management
operations under a single namespace.

**Decision:** convert `gallery` from a flat command into a sub-command group
using `argparse` nested subparsers. Preserve backwards-compatibility by
keeping the bare `gallery` invocation aliased to `gallery build`.

### New Subcommand Surface

All commands accept `--gallery DIR` (default `gallery`).

| Subcommand | Purpose |
| --- | --- |
| `gallery build` | (Existing behavior) regenerate `index.html` + thumbnails. Aliased from bare `gallery`. |
| `gallery query` | Filter items by various criteria, print results to stdout. |
| `gallery show ID` | Pretty-print full metadata for a single item. |
| `gallery tag ID [ID...] --add T [T...]` | Add tag(s) to one or more items (deduped, order-preserving). |
| `gallery untag ID [ID...] --remove T [T...]` | Remove specific tag(s). `--all` clears the list. |
| `gallery set ID --title VALUE` (etc.) | Update a string field (`title`, `prompt`, `conversation_link`, `created-at`). One named flag per supported field; argparse `--field VALUE` form, not literal `--field=value`. |
| `gallery unset ID --field` | Set a field to `None` / clear (`title`, `prompt`, `conversation_link`, `tags`, `thumbnails`). |
| `gallery mv ID NEW-FILENAME` | Atomically rename an item's image file, all thumbnail tiers (small/medium/large), and update `filename` + `thumbnails` + `thumbnail` in metadata. Path-traversal-safe; fails loud on collision. See "Atomic rename" under Design Decisions. |
| `gallery rm ID [ID...]` | Delete items + their image file + all thumbnails (with `--dry-run` and confirmation, honoring root `-y`). |
| `gallery stats` | Print counts (total items, with/without tags, with/without prompts, distinct tags, top-N tags, total bytes). |
| `gallery export [--format=json\|csv\|tsv]` | Stream filtered results in machine-readable form. |
| `gallery affinity` | Recompute the affinity index (see Task 7). |
| `gallery dedupe` | Detect and report duplicate `checksum` values; `--delete` to remove all but the oldest. |
| `gallery verify` | Walk metadata, report missing image files and orphan thumbnails. |
| `gallery prune-thumbs` | Delete thumbnails whose image no longer exists in metadata or on disk. |

### `gallery query` Filters (shared with `export`)

- `--id ID` (repeatable)
- `--tag T` / `--no-tag T` (repeatable; AND logic across `--tag`)
- `--has-tags` / `--no-tags` — items with any / no tags
- `--has-prompt` / `--no-prompt`
- `--title-contains TEXT` (case-insensitive)
- `--prompt-contains TEXT`
- `--conversation-id ID`
- `--extra KEY=VALUE` (repeatable; matches against `GalleryItem.extra` keys, e.g. `--extra model=dall-e-3`). This is the addressable form of "query by model" until/unless `model` is promoted to a first-class field. String-equality match by default; we explicitly do not commit to numeric comparison or globbing in this batch.
- `--since YYYY-MM-DD` / `--until YYYY-MM-DD` (inclusive, against `created_at`)
- `--missing-file` — metadata entries whose `images/<filename>` is absent
- `--missing-thumbs` — entries whose thumbnail files are absent
- `--limit N` / `--sort=date|title|affinity` / `--reverse`
- `--format=table|ids|json` (default `table`; `ids` writes one per line for piping to `gallery rm`/`tag`/`untag`)

### Files Touched

- `src/chatgpt_library_archiver/cli/app.py` — register the gallery group; collapse legacy default.
- `src/chatgpt_library_archiver/cli/commands/gallery.py` — replace single command with a group dispatcher; split each subcommand into its own `_handle_*` method on `GalleryCommand`.
- `src/chatgpt_library_archiver/__main__.py` — wire up new dependency callables (`item_query`, `item_mutator`, `item_remover`, `gallery_stats`, `gallery_verifier`, `dedupe_runner`).
- New module `src/chatgpt_library_archiver/management.py` — pure-Python query/mutation/deletion helpers operating on `GalleryItem` lists.
- `src/chatgpt_library_archiver/metadata.py` — add small helpers `find_by_id(items, id)`, `partition_by_ids(items, ids)`.
- `src/chatgpt_library_archiver/thumbnails.py` — add `delete_thumbnails(gallery_root, filename)` for `rm` and `prune-thumbs`.
- `tests/test_management.py` (new) and additions to `tests/test_cli.py`.
- `README.md` — add new subcommand reference table.
- `CHANGELOG.md` — entry under "Added".

### Design Decisions

- **Nested subparsers, not flat**: `gallery <verb>` keeps the namespace clean and avoids polluting the top-level CLI. The default `parser.set_defaults(command_handler=download_cmd.handle)` in [cli/app.py](src/chatgpt_library_archiver/cli/app.py#L60) is unaffected.
- **Bare-`gallery` alias mechanism**: argparse nested subparsers do not natively dispatch a default child. We register the gallery subparsers with `required=False` and `parser_gallery.set_defaults(gallery_verb=None, gallery_handler=_handle_build)`. Each verb subparser then calls `set_defaults(gallery_verb="<verb>", gallery_handler=_handle_<verb>)`. The dispatcher invokes `args.gallery_handler(args)`. A regression test (`tests/test_cli.py::test_gallery_bare_aliases_build`) asserts that `chatgpt-library-archiver gallery` (no verb) still rebuilds.
- **Atomic writes**: every mutation reuses [`save_gallery_items`](src/chatgpt_library_archiver/metadata.py#L206) (atomic via tempfile + `os.replace`).
- **Atomic rename (`gallery mv`)**: rename touches three locations — `images/<old>`, `thumbs/{small,medium,large}/<old>`, and the metadata entry's `filename` / `thumbnail` / `thumbnails` fields. Sequence:
    1. Validate target name (path-traversal safe, no directory separators, no collision with an existing image or thumbnail).
    2. Compute old/new path pairs for the original and each present thumbnail tier (only tiers that exist on disk are renamed — missing thumbs are left missing, same as today).
    3. `os.rename` each pair in order: original image first, then `small`/`medium`/`large` thumbnails. Track successful renames in a list.
    4. If any `os.rename` raises, **roll back** by reversing every successful rename (best-effort `os.rename` back to its original path) and re-raise. Metadata is not written until all on-disk renames succeed.
    5. After all renames complete, update `item.filename`, `item.thumbnail` (legacy single-string field if present), and `item.thumbnails` to point at the new filename, then call `save_gallery_items` (atomic).
    6. If the metadata write itself fails after the on-disk renames succeeded, perform the same reverse-rename rollback and surface the error. The user sees a non-zero exit and an unchanged gallery on disk.
  Failure mode is **fail-loud with rollback** — partial state on disk is treated as a bug, not a feature.
- **Confirmation**: `rm`, `unset --tags` (with cardinality > 0), and `dedupe --delete` prompt unless root `-y` was passed (use the existing `ARCHIVER_ASSUME_YES` env var pattern from [`__main__.py`](src/chatgpt_library_archiver/__main__.py#L40)). `mv` does not prompt (rename is reversible by running `mv` again).
- **Path-traversal safety**: when deleting or renaming files, resolve `gallery_root / "images" / filename` and assert the result is `.is_relative_to(images_dir.resolve())` (mirrors [`incremental_downloader._sanitize_id`](src/chatgpt_library_archiver/incremental_downloader.py#L32) defenses).
- **Output formats**: `query --format=ids` produces newline-delimited IDs so users can pipe `gallery query --no-tags --format=ids | xargs chatgpt-library-archiver gallery rm`.

### Edge Cases

- Updating tags: must run through [`tagger.normalize_tag`](src/chatgpt_library_archiver/tagger.py#L126) so CLI input matches AI-generated form.
- `rm` of a missing image file: warn but still drop the metadata entry.
- `rm` should not delete external symlinked images — refuse to follow symlinks (pattern from [importer.py](src/chatgpt_library_archiver/importer.py#L267)).
- `mv` target name collisions: if `images/<new>` already exists, fail before any rename; do not overwrite. Similarly fail if any thumbnail destination would collide.
- `mv` rollback: if a partial rename fails, the helper restores the renames it already performed in reverse order. If even the rollback fails (extremely rare — disk full mid-operation), log every still-renamed pair to stderr so the operator can recover manually.
- `verify` must tolerate optional WebP thumbnails (extension differs).
- `dedupe` uses `checksum` when present, otherwise falls back to byte-for-byte hash recomputation (only when `--rehash` flag passed).
- Idempotency: `tag --add` of an existing tag is a no-op, exit code 0.
- `set --created-at` must accept both ISO-8601 strings and Unix timestamps; reuse [`metadata.normalize_created_at`](src/chatgpt_library_archiver/metadata.py#L22).

### Test Plan

- Unit tests for each `management.py` helper (query filtering, `--extra` matching, set/unset, rm with file cleanup, dedupe, `mv` happy-path and rollback).
- `tests/test_cli.py`: add tests verifying the subcommand dispatch routes to the right handler with the right kwargs (mirrors existing `test_cli_*` patterns). Includes `test_gallery_bare_aliases_build` to lock in the bare-`gallery` alias.
- Integration test: write a fixture metadata file, invoke `gallery rm` via the CLI entrypoint, assert metadata + images + thumbs are gone.
- Integration test: invoke `gallery mv ID NEW-NAME`; assert all thumb tiers and the image file are renamed and metadata is updated. Negative test: simulate a thumbnail rename failure (e.g. read-only thumbnail directory or pre-existing collision) and assert the original image was renamed back, metadata is unchanged, and the command exits non-zero.
- Edge case tests: deleting an item whose image file was already removed manually; rm with `-y`; rm without confirmation aborts cleanly; `mv` with a name containing `/` is rejected; `mv` to an existing filename is rejected before any rename happens.

### Doc / ADR

- ADR recommended (see Task ADRs section): `0003-gallery-management-cli.md`.
- README "Usage" section needs a new sub-section.

---

## Task 2 — Tag Merge Bug Fix

### Scope

When `import --tag foo --tag-new` runs, the user-provided `foo` tag is
clobbered by the OpenAI response. Same defect on `download --tag-new` if a
source item already arrived with `tags`.

### Root Cause

In [tagger.py](src/chatgpt_library_archiver/tagger.py#L219) inside
`tag_images.process()`:

```python
item.tags = tags
```

This unconditionally overwrites the existing `item.tags` (populated by
`ImportConfig.tags` in [importer.py](src/chatgpt_library_archiver/importer.py#L65), or by the API payload during download) with the AI-generated list.

### Fix

Replace `item.tags = tags` with an order-preserving merge that prefers the
user's existing tags first, then appends new AI tags not already present:

```python
existing = item.tags or []
seen = {t for t in existing}
merged = list(existing)
for t in tags:
    if t not in seen:
        merged.append(t)
        seen.add(t)
item.tags = merged
```

This is the minimal, local fix. Existing tags should already have been
normalized via [`tagger.normalize_tag`](src/chatgpt_library_archiver/tagger.py#L126) at ingestion time. Today
[`importer.ImportConfig.__post_init__`](src/chatgpt_library_archiver/importer.py#L65) splits comma-separated
input but does not lowercase/normalize — Task 2 also adds a `normalize_tag` call there so user-supplied
tags pass through the same canonicalization the AI tags use, preventing case-only duplicates.

Note: there is also a separate [tag_normalizer.py](src/chatgpt_library_archiver/tag_normalizer.py) module
used by the `gallery normalize-tags` workflow. The fix uses `tagger.normalize_tag` (lowercase + strip)
for ingestion-time canonicalization; we are not introducing a duplicate normalization path.

### Files Touched

- `src/chatgpt_library_archiver/tagger.py` — inside `tag_images.process()`, modify the assignment.
- `src/chatgpt_library_archiver/importer.py` — call `normalize_tag` in `ImportConfig.__post_init__` so user CLI tags pass through the same normalization as AI tags before merging (prevents the "user typed `Sunset` and AI returned `sunset` so we end up with both" duplication).
- `tests/test_tagger.py` — add regression test covering merge behavior.
- `tests/test_importer.py` — add test for `import --tag --tag-new` merge.
- `CHANGELOG.md` — entry under "Fixed".

### Edge Cases

- Case-only differences: AI returns lowercase, user typed mixed-case. Mitigated by normalizing user tags through `normalize_tag` in `ImportConfig.__post_init__` (see above).
- Empty user tags: behavior is unchanged from today (just the AI tags).
- Empty AI response: existing user tags retained — no longer "blanked out".
- Re-tagging (`tag --all` or `tag --ids`): the merge means re-tagging never strips manual tags. This is desired per the user's intent. If a user wants to truly reset, they call `tag --remove-ids ...` first.

### Test Plan

- New unit test in `tests/test_tagger.py` (`test_tag_images_merges_existing_tags`): seed a `GalleryItem` with `tags=["manual"]`, mock OpenAI to return `"ai-one, ai-two"`, assert the saved item ends with `["manual", "ai-one", "ai-two"]`.
- Test deduplication: existing `["sunset"]` + AI `"sunset, beach"` → `["sunset", "beach"]`.
- Test order preservation across multiple existing tags.
- Importer integration test that exercises `--tag` + `--tag-new`.

### Doc / ADR

- No ADR needed (a bug fix).
- CHANGELOG only.

---

## Task 3 — Full-Resolution Images in `gallery-full` List Mode

### Scope

The "Full size" gallery list mode should serve the original image, not the
400 px `large` thumbnail. The lightbox viewer (`#viewerImg` in
[gallery_index.html](src/chatgpt_library_archiver/gallery_index.html#L523), JS reference at
[L999](src/chatgpt_library_archiver/gallery_index.html#L999)) already loads `item.src` which is
`images/<filename>`, so the **lightbox is unaffected**. The defect is
specifically in the **`gallery-full` list-mode view**:
`sizeKeyToWidth.full = 400` in [gallery_index.html:539](src/chatgpt_library_archiver/gallery_index.html#L539)
and `resolveThumbnails` ([L574](src/chatgpt_library_archiver/gallery_index.html#L574)) falls back to
`fullSrc` only if `thumbs.full` is unset, but `updateThumbnailsForSize('full')` then assigns
`data-thumb-full` (which we never populated, so it falls through to the original image already).
However, `srcset` still advertises only `small/medium/large` widths and `sizes` is reported as
`400px`, causing the browser to pick `large` for `gallery-full`.

### Decision: serve the original; do **not** add an `xlarge` tier

Justification:

1. **Disk cost** is the main reason new tiers exist. The originals already exist in `images/` and downloads are gated by an inline `max_bytes=100 * 1024 * 1024` cap (no module-level constant) at [incremental_downloader.py:106](src/chatgpt_library_archiver/incremental_downloader.py#L106). Pre-rendering 2560 px thumbnails for every image roughly doubles total thumb storage for a marginal load-time win.
2. **Quality**: modern phone DPI (iPhone 16 Pro Max 1290 × 2796 native, ~3x DPR; Pixel 9 Pro 1280 × 2856; S25 Ultra 1440 × 3120) means a 2048 px tier still loses detail vs. originals when a user pinch-zooms in the lightbox. Originals win once the network can deliver them.
3. **Pipeline complexity**: every thumbnail consumer ([`thumbnails.create_thumbnails`](src/chatgpt_library_archiver/thumbnails.py#L231), [`thumbnail_relative_paths`](src/chatgpt_library_archiver/thumbnails.py#L101), [`ensure_thumbnail_metadata`](src/chatgpt_library_archiver/thumbnails.py#L320), gallery JS) would need a fourth size. Skipping a tier keeps the change small.
4. **Local-first**: the gallery is browsed via `file://` for many users (per the [gallery skill](.github/skills/gallery-html-patterns/SKILL.md)), so latency is negligible.
5. **Future hook**: if a user really needs an intermediate tier, we can add it later without breaking metadata (the `thumbnails` map is already a dict keyed by size).

### Implementation

In `gallery_index.html`:

- `sizeKeyToWidth.full`: change `400` to a high value (e.g. `2400`) so `sizes` math reports the right hint.
- `srcset`: include the original at its intrinsic width when in full mode. Practical fix: append `imgPath + ' 2400w'` to `srcset` (the browser uses it when `sizes` advertises a wider viewport, e.g. when the user picks Full). To avoid wasting bandwidth in grid mode, set `srcset` based on the current size key: small/medium/large omit the original; full mode includes it.
- `data-thumb-full` should already equal `imgPath`. Ensure `resolveThumbnails` returns `imgPath` for `full` (it does — see [L582](src/chatgpt_library_archiver/gallery_index.html#L582)).
- `updateThumbnailsForSize('full')` should set `img.src = imgPath` directly rather than relying on the cascade.
- `rebuildViewerData()` already uses `imgPath` for `viewerData[i].src` so the **lightbox itself** is unaffected. Do not touch it; the user's complaint actually targets `gallery-full`.

### Files Touched

- `src/chatgpt_library_archiver/gallery_index.html` — `sizeKeyToWidth`, `updateThumbnailsForSize`, `createCard` (the `srcset` setter).
- `tests/test_gallery.py` — add a smoke test that opens the generated HTML, parses with stdlib `html.parser`, and asserts the rendered `srcset` for at least one card includes the original `images/<filename>` token when full mode is the default.
- `CHANGELOG.md`.

### Edge Cases

- Corrupted/very large originals: respect existing `Image.MAX_IMAGE_PIXELS = 200_000_000` for any thumbnail regen, but the JS path doesn't decode in Python — just trusts the file. Browser may run out of memory on extreme files; document this in CHANGELOG as a known limitation.
- WebP-only galleries: `imgPath` always points to the original (PNG/JPEG/etc.), regardless of WebP thumbs setting, so this is unaffected.
- AI-generated images often have intrinsic widths in the 1024–2048 range — for those, "full" is genuinely full; no upscaling.

### Test Plan

- `tests/test_gallery.py`: assert HTML contains the original-image entry in `data-thumb-full`.
- Manual smoke test: open the generated gallery on iPhone 15+ DPI, confirm pinch-zoom in the lightbox shows native pixels (browser DevTools "device pixel ratio" emulation suffices for CI-free verification).

### Doc / ADR

- ADR recommended: `0002-full-resolution-lightbox.md` (decision rationale: original vs. xlarge tier).
- CHANGELOG entry.

---

## Task 4 — Pinch-Closes-Lightbox Bug

### Scope

In [gallery_index.html](src/chatgpt_library_archiver/gallery_index.html#L1119)
the viewer's `touchstart` listener returns early when
`e.touches.length !== 1`, but the matching `touchend` only checks
`e.changedTouches.length !== 1`. When the user pinches: the second finger's
`touchend` arrives separately, has `changedTouches.length === 1`, no
`touchStartX`/`touchStartY` was recorded, and the swipe-distance check
fails so the `else` branch fires `closeViewer()`.

### Fix Strategy

Switch to **Pointer Events** with explicit pointer tracking:

- `pointerdown`: push `{id, x, y}` into `activePointers` (a `Map`).
- `pointermove`: update; mark `moved = true` if displacement exceeds 10 px.
- `pointerup` / `pointercancel`:
  - If `activePointers.size > 1` at any point during this gesture (track via a flag `wasMultiTouch`), release without closing.
  - If `wasMultiTouch === false`, no movement, single pointer, primary button (or touch) → invoke `closeViewer()`.
  - If single pointer with horizontal movement >50 px > vertical, treat as swipe (same as today).
- Add `touch-action: manipulation` to `#viewer` so the browser handles native pinch-zoom and pan-after-zoom on iOS without firing synthetic double-tap-zoom or 300 ms click delay. **Why `manipulation`, not `pinch-zoom`:** per the CSS Touch Action spec, the literal value `pinch-zoom` disables `pan-x` and `pan-y`, so once the user pinches in, they cannot pan around the zoomed image — strictly worse than today. `manipulation` is the standard "allow pinch + pan, suppress double-tap zoom and click delay" combo and matches what we want for a media viewer. (`pan-x pan-y pinch-zoom` is functionally equivalent and may be used if a specific browser proves quirky; document the final choice in the CHANGELOG.) Verify on real iOS Safari before merging.
- Keep the existing keyboard handler unchanged.

This eliminates the dual-listener inconsistency and works on desktop (mouse), tablets (Apple Pencil), and phones uniformly.

### Files Touched

- `src/chatgpt_library_archiver/gallery_index.html` — rewrite the touch-handler block (currently at lines ~1119–1140). Add CSS `#viewer { touch-action: manipulation; }` near the existing `#viewer` rules at [L337](src/chatgpt_library_archiver/gallery_index.html#L337).
- `tests/test_gallery.py` — assert the rendered HTML no longer contains `touchstart`/`touchend` viewer listeners (regression sentinel) and contains the new `pointerdown` listener.
- `CHANGELOG.md`.

### Edge Cases

- iOS Safari fires synthetic `click` events after `touchend`. The viewer's existing `click` listener will still try to close; gate it the same way (require `wasMultiTouch === false` and stash that flag on the viewer element).
- A swipe that briefly registers a second touch (palm reject) should not close. The `wasMultiTouch` latch covers it.
- Trackpad pinch on macOS sends `wheel` with `ctrlKey`, not pointer events — out of scope.
- Pointer Events are widely supported; a browser without `PointerEvent` (very old) would lose the close-on-tap behavior. Acceptable; we keep the close button visible and keyboard handler.

### Test Plan

- Unit-style: parse `gallery_index.html`, assert `pointerdown` / `pointerup` listeners exist on `#viewer` and `touchstart`/`touchend` are gone.
- Manual smoke test: pinch-zoom on a phone (or browser device emulator with multi-touch). Verify the viewer stays open. Single-tap closes.

### Doc / ADR

- No ADR.
- CHANGELOG "Fixed".

---

## Task 5 — Mobile Hover-Panel UX

### Scope

The CSS `.image-card:hover .meta` rule
([gallery_index.html:104](src/chatgpt_library_archiver/gallery_index.html#L104)) shows the title/tags overlay on hover. On
touch devices, browsers synthesize hover on first tap, so any scroll-touch
that grazes a card pops the panel. Replace with explicit interaction.

### Design

1. **Gate the hover rule** with `@media (hover: hover) and (pointer: fine)` so it never applies on touch devices:

    ```css
    @media (hover: hover) and (pointer: fine) {
      .image-card:hover .meta,
      .image-card:focus-within .meta { display: block; }
    }
    ```

2. **Add a coarse-pointer interaction**: on `(hover: none) and (pointer: coarse)`:
    - Plain tap → existing behavior (open lightbox via the link's click handler).
    - Long-press (≥500 ms, no movement >8 px) → show a full-screen modal with the item's metadata; suppress the click that would otherwise fire.
    - Scroll/pan → no overlay.

3. **Modal markup** (added once near the bottom of `<body>`, beside the existing `#viewer`):

    ```html
    <div id="metaModal" role="dialog" aria-modal="true" aria-label="Image metadata" tabindex="-1" hidden>
      <button class="meta-modal-close" type="button" aria-label="Close">&times;</button>
      <div class="meta-modal-body">
        <h2 id="metaModalTitle"></h2>
        <p id="metaModalCreated"></p>
        <p id="metaModalPrompt"></p>
        <ul id="metaModalTags" class="tag-pill-list"></ul>
        <a id="metaModalConv" target="_blank" rel="noopener">View conversation</a>
        <a id="metaModalRaw" target="_blank">Open image</a>
      </div>
    </div>
    ```

4. **Modal styling**: full-viewport overlay, same dark backdrop pattern as `#viewer`, scrollable body for long prompts, dismissed by close button, backdrop tap, or `Escape`.

5. **Long-press detection**: on each `.image-card` (delegated at the gallery container) listen for `pointerdown` on coarse pointers; start a 500 ms timer; cancel on `pointermove > 8px` or `pointerup` before the timer fires. When the timer fires, capture the pointer and open the modal; on the subsequent `click`, swallow it (`event.preventDefault()`, `event.stopPropagation()`).

6. **Detection**: use `window.matchMedia('(hover: none) and (pointer: coarse)').matches` at runtime (not just CSS) so the JS handler only attaches on touch devices.

### Files Touched

- `src/chatgpt_library_archiver/gallery_index.html` — add the media query, the modal markup, JS handler, and the long-press detector.
- `tests/test_gallery.py` — assert the rendered HTML contains the new modal element and the media-query gate (sentinel, not behavior).
- `CHANGELOG.md`.

### Edge Cases

- A device that responds to both touch and mouse (iPad with Magic Keyboard, Surface): `(any-hover: hover)` resolves true; CSS hover stays. Acceptable. Long-press still works as a power-user shortcut.
- User starts a tap, drags out (scrolling) — pointermove cancels the timer, no modal, scroll completes. Click is not suppressed (we only suppress on timer-fired).
- Existing `<a>` link inside cards — long-press on iOS triggers the system context menu by default; suppress with CSS `-webkit-touch-callout: none;` on `.image-card`.
- Keyboard users: tag pills already get `:focus-within`. We **drop** the `i`-key shortcut from the original draft — it would collide with literal `i` typed into the search box and adds a global binding for marginal value. Keyboard users on touch hardware can still focus a card and activate it normally; the long-press path is for touch only.
- Existing tag-pill click handler must still work without opening the modal (event happens after `pointerup`, so the timer-fired flag must be reset before the synthetic click bubbles to the pill).

### Test Plan

- HTML sentinel test in `tests/test_gallery.py` verifying the modal markup exists and the media query is present.
- Manual smoke test on iOS Safari, Chrome Android (latest), and a desktop browser with DevTools mobile emulation:
  - Tap card → lightbox opens, no modal.
  - Long-press card → modal opens, no lightbox.
  - Scroll past cards → no modal, no lightbox, no `:hover` overlay.

### Doc / ADR

- No ADR (UX bug fix; the design is documented inline in this plan).
- CHANGELOG "Changed" entry.

---

## Task 6 — Parallelize Per-Image Thumbnail Generation

### Scope

[`thumbnails.regenerate_thumbnails`](src/chatgpt_library_archiver/thumbnails.py#L353) is *already* parallelized via
`ProcessPoolExecutor`. However, the **per-image** code path used by
[`incremental_downloader.download_image`](src/chatgpt_library_archiver/incremental_downloader.py#L77) and [`importer._import_one_image`](src/chatgpt_library_archiver/importer.py#L218) calls
[`thumbnails.create_thumbnails`](src/chatgpt_library_archiver/thumbnails.py#L231) directly, which iterates the three sizes
sequentially in a single process.

Two layers of parallelization opportunity:

- **Layer A** (within one image): generate the small/medium/large variants in parallel for a single source. Limited gain because Pillow already shares the decoded base image, so the bottleneck is encoding 3 small files. Skip — would require re-decoding.
- **Layer B** (across images during import / download): images are downloaded in a `ThreadPoolExecutor`. Thumbnail generation runs inline on the same thread (CPU-bound, holds the GIL because Pillow releases the GIL only during native ops). Move thumbnail work to a `ProcessPoolExecutor`.

Layer B is the right target.

### Design

1. Add a new public helper `thumbnails.create_thumbnails_pool(...)` that wraps a long-lived `ProcessPoolExecutor` and exposes `submit(source, dest_map, webp) -> Future[str]`. Use `multiprocessing.get_context()` for explicit context selection (fork vs. spawn parity).
2. In `incremental_downloader.download_image`, do not call `create_thumbnails` directly; instead return the source path and dest map from a simpler "download only" function and let the orchestrator submit thumbnail work to the pool.
3. In `importer._import_one`, same pattern.
4. **Default worker count**: `min(os.cpu_count() or 1, 8)` to match `regenerate_thumbnails`. Override via a new `--thumb-workers` flag on both `download` and `import` commands (named to match the existing `thumbs/` directory and to align with the existing `--max-workers` / `--tag-workers` naming style — short, hyphenated, scope-prefixed).
5. **Error handling**: per-future exception captured and reported via `progress.report_error`, matching the existing pattern in `regenerate_thumbnails` ([thumbnails.py](src/chatgpt_library_archiver/thumbnails.py#L486)).
6. **Skip-if-exists**: the per-image pre-flight check already exists in `regenerate_thumbnails`. Replicate it in the new `create_thumbnails_pool.submit` so we don't regenerate thumbnails the downloader/importer already produced.
7. **Progress reporting**: keep using the manager-queue mechanism already implemented for `regenerate_thumbnails` (`_consume_status_messages`).
8. **Interrupt handling (Ctrl+C / SIGINT)**: the pool wrapper installs no custom signal handler — the default Python behavior raises `KeyboardInterrupt` in the main thread. The `finally` block must call `executor.shutdown(wait=False, cancel_futures=True)` so pending thumbnail jobs are dropped and the pool tears down within ~1 s on macOS spawn (rather than the multi-second join the context-managed `with ProcessPoolExecutor()` form imposes). In-flight workers finish their current image (Pillow encode is short; killing mid-write would corrupt thumbnails). Any thumbnails already written to disk are preserved — the next `gallery build` or re-run picks them up via the skip-if-exists check. The CLI exits with a non-zero status (`130` for SIGINT, matching shell convention). Document this in the CHANGELOG and add a smoke test that submits a long batch, raises `KeyboardInterrupt`, and asserts (a) the pool shut down, (b) at least one thumbnail file exists on disk, and (c) the process exit code is non-zero.

### Files Touched

- `src/chatgpt_library_archiver/thumbnails.py` — extract a `_ThumbnailPool` class wrapping the executor + status thread; refactor `regenerate_thumbnails` to use it.
- `src/chatgpt_library_archiver/incremental_downloader.py` — split download from thumbnail generation; share a single pool across the run.
- `src/chatgpt_library_archiver/importer.py` — same.
- `src/chatgpt_library_archiver/cli/commands/download.py`, `cli/commands/import_command.py` — add `--thumbnail-workers` option.
- `tests/test_thumbnails.py` — already has parallel coverage; add tests for `create_thumbnails_pool`.
- `tests/test_importer.py`, `tests/test_end_to_end.py` — assert thumbnails generated under concurrency.
- `CHANGELOG.md`.

### Design Decisions

- **Why ProcessPool, not ThreadPool**: Pillow encoding is partially CPU-bound and partially GIL-released, but multi-process gives more headroom and matches the existing `regenerate_thumbnails` design. The fork cost is amortized over the full run because we keep the pool alive.
- **Pool lifetime**: a single pool spans the whole import / download run. Created lazily on first thumbnail submission, closed in `finally` via `shutdown(wait=False, cancel_futures=True)` on the interrupt path and `shutdown(wait=True)` on the clean-exit path.
- **Pickling**: `Path` and `dict[str, Path]` pickle cleanly. `StatusReporter` does not — that's why the existing implementation uses a `Manager().Queue()` for status.

### Edge Cases

- Worker process crash: future raises, we report-error and continue. The pool replaces the worker automatically.
- ICC profile conversion (`_ensure_srgb`): runs per-image inside the worker, no shared state — safe.
- `Image.MAX_IMAGE_PIXELS = 200_000_000` is set at module import in [thumbnails.py](src/chatgpt_library_archiver/thumbnails.py#L31), inherited by spawned workers via re-import.
- Windows `spawn` semantics: use `if __name__ == "__main__":` guards already in place; no new top-level mutables.
- Tests must not deadlock: `pytest-cov` + multiprocessing requires `concurrencyfix`. Existing `test_thumbnails.py` already passes this — preserve the pattern.

### Test Plan

- Unit: `test_create_thumbnails_pool_basic` (5 images, 2 workers, all thumbs produced).
- Unit: `test_create_thumbnails_pool_skips_existing` (pre-create one thumb, assert mtime unchanged when not forced).
- Unit: `test_create_thumbnails_pool_handles_corrupt_image` (one bad PNG; pool reports error, others succeed, run finishes).
- Unit: `test_create_thumbnails_pool_shutdown_on_interrupt` — submit a batch, raise `KeyboardInterrupt` from the orchestrator, assert the pool is torn down promptly (`shutdown` was called with `cancel_futures=True`), at least one thumbnail file remains on disk, and the wrapper re-raises so the CLI exits non-zero.
- End-to-end: `test_import_uses_thumbnail_pool` (mock or otherwise verify ProcessPoolExecutor is used).

### Doc / ADR

- No ADR (extension of the existing `regenerate_thumbnails` pattern).
- CHANGELOG "Changed".

---

## Task 7 — Tag Affinity (Similarity) Sort

### Scope

Provide a sort mode that places images with overlapping tags adjacent to one
another. Goal: scrolling the gallery feels topical, not random.

### Algorithmic Decision

**Recommended algorithm: Greedy nearest-neighbor traversal over Jaccard similarity, seeded by the most-tagged item.**

Rationale (compared with alternatives):

| Approach | Quality | Perf (N=10k) | Complexity | External deps |
| --- | --- | --- | --- | --- |
| **Greedy NN (chosen)** | Good local clustering | O(N²) worst-case, fine for ≤20k items | ~50 lines pure Python | None |
| Hierarchical clustering | Best clusters globally | O(N²) memory, slow above 5k | ~200 lines + lots of edge cases | Optional `scipy` |
| MDS / UMAP 1D embedding | Best continuum | Slow, stochastic | High | `numpy`, `umap-learn` (heavy deps) |
| TF-IDF cosine + greedy | Marginal improvement | Same as Jaccard | Same | None |
| Tag-bucket sort (group by primary tag) | Coarse | O(N log N) | ~30 lines | None |

The chosen approach:

1. Compute a tag set for each item (already on `GalleryItem.tags`; convert to `frozenset`).
2. Drop items with no tags into a "tail" bucket sorted by `created_at`.
3. Pick the seed: item with the most tags in the most-frequent global tag (gives the densest part of the graph as an anchor). **The seed-choice rationale and rejected alternatives (lowest-degree seed, deterministic-by-id seed, arbitrary first item) are documented in `docs/adr/0001-tag-affinity-sort.md`.**
4. Iteratively pick the unvisited item with the highest Jaccard similarity to the previous item; tiebreak on shared tag count, then on `created_at` desc.
5. Append the no-tag tail at the end.
6. Store the result index as `affinity_index` (0-based) on each item.

Jaccard cost is `|A ∩ B| / |A ∪ B|`. Implementation uses an inverted index (`tag → set[item_id]`) so each step only scans candidates sharing ≥1 tag with the current item — typically O(k·N) per step, ~O(N²/c) overall. Acceptable for galleries up to ~20k items in well under a second on a laptop.

### Where the computation lives

**Decision: precompute server-side (Python), not in JavaScript.**

Reasons:

- Static gallery loads metadata as a frontloaded JS variable; doing O(N²) work at load time on a phone is bad UX.
- The metadata file is rebuilt anyway during `gallery build` and after `tag` operations.
- A precomputed `affinity_index` field also lets external CLI tools (`gallery query --sort=affinity`) consume it.
- Recomputing only happens when tags change — opportunistic.

### Data Shape

Add an integer field `affinity_index` to `GalleryItem` (default `None`).
Persisted in `metadata.json`. The gallery viewer adds a new sort option:

```html
<option value="affinity">Tag similarity</option>
```

with a JS sort comparator:

```js
case 'affinity':
  sorted.sort(function(a, b) {
    var ai = a.affinity_index, bi = b.affinity_index;
    if (ai == null && bi == null) return 0;
    if (ai == null) return 1;
    if (bi == null) return -1;
    return ai - bi;
  });
  break;
```

### When the index is recomputed

- During `gallery build` (called by `download`, `import`, and `gallery` commands) — opportunistic, only if any item lacks `affinity_index` or the global tag set changed (cheap dirty check: hash of all tag-sets vs. a stored fingerprint in a small `gallery/.affinity-cache` JSON file).
- Explicitly via `gallery affinity --recompute` (Task 1).
- After `tag` / `tag --remove-*` / `tag --consolidate` — mark dirty (write a sentinel) so the next `gallery build` recomputes.

### Files Touched

- `src/chatgpt_library_archiver/affinity.py` (new) — pure-function `compute_affinity_indices(items: list[GalleryItem]) -> None` that mutates in place.
- `src/chatgpt_library_archiver/metadata.py` — add `affinity_index: int | None = None` to `GalleryItem`, plumb through `from_dict` ([L104](src/chatgpt_library_archiver/metadata.py#L104)) / `to_dict` ([L166](src/chatgpt_library_archiver/metadata.py#L166)). Add `affinity_index` to the explicit excluded-keys set in `from_dict` so it does **not** also appear in the `extra` dict on round-trip.
- `src/chatgpt_library_archiver/gallery.py` — call `compute_affinity_indices` (with dirty-check) inside `generate_gallery`.
- `src/chatgpt_library_archiver/tagger.py`, `tag_normalizer.py` — touch the dirty sentinel after a successful run.
- `src/chatgpt_library_archiver/gallery_index.html` — new sort option + comparator.
- `tests/test_affinity.py` (new) — unit tests for the algorithm.
- `tests/test_gallery.py` — integration: items with overlapping tags end up adjacent.
- `tests/test_metadata.py` — `affinity_index` round-trips through `to_dict`/`from_dict`.
- `CHANGELOG.md`.
- `docs/adr/0001-tag-affinity-sort.md`.

### Edge Cases

- Items with no tags: assigned `affinity_index = None`, sorted to the end with stable date-desc tiebreaker on the JS side.
- All items share zero tags: greedy selection still works (similarity 0 ties), tiebreaker on `created_at` desc.
- Single-item gallery: `affinity_index = 0`.
- Large galleries (>50k items): document a fallback to bucket-sort by primary tag if N exceeds a threshold (e.g. `if len(items) > 50_000: use_bucket_strategy()`).
- Determinism: same input must yield the same output — sort tag sets, sort tiebreakers, sort initial seed candidates.
- Tag normalization: must occur before similarity (already enforced via `normalize_tag` at write time).

### Test Plan

- Algorithm tests:
  - Empty input → no error.
  - All-disjoint items → result preserves date order.
  - Three groups of overlapping tags → items in each group cluster contiguously.
  - Determinism: shuffle input, recompute, assert ordering is the same.
- Round-trip test: write items, reload, `affinity_index` preserved.
- **Back-compat round-trip test (`tests/test_metadata.py`)**: load a metadata file produced by a hypothetical newer version that includes both `affinity_index` and an arbitrary unknown key (e.g. `future_field`); save it back; reload; assert (a) `affinity_index` round-trips correctly via the typed field, (b) `future_field` survives in `GalleryItem.extra` exactly as written, and (c) re-serialization preserves the unknown key. This locks in the existing `extra` preservation contract from [metadata.py](src/chatgpt_library_archiver/metadata.py#L104) so a downgrade after `gallery build` does not silently drop unrecognized keys.
- Performance test (marked slow): 5000 random items run within a budget (e.g. 2s on CI).
- Gallery HTML test: assert the new sort option exists and the comparator handles `null` gracefully.

### Doc / ADR

- ADR `0001-tag-affinity-sort.md` recommended. Must cover: algorithm choice (Jaccard greedy-NN vs. alternatives), server-side precompute decision, scaling fallback for >50k items, **and explicit justification of the densest-cluster seed choice with rejected alternatives (lowest-degree seed, deterministic-by-id seed, arbitrary first item)**.
- README usage update.
- CHANGELOG "Added".

---

## File-Touch Matrix

Tasks: 1=Mgmt CLI, 2=Tag merge, 3=Full lightbox, 4=Pinch fix, 5=Mobile UX, 6=Thumb pool, 7=Affinity.

| File | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | - | - | - | - | - | - | - |
| `src/chatgpt_library_archiver/cli/app.py` | ✏️ |   |   |   |   |   |   |
| `src/chatgpt_library_archiver/cli/commands/gallery.py` | ✏️ |   |   |   |   |   |   |
| `src/chatgpt_library_archiver/cli/commands/download.py` |   |   |   |   |   | ✏️ |   |
| `src/chatgpt_library_archiver/cli/commands/import_command.py` |   |   |   |   |   | ✏️ |   |
| `src/chatgpt_library_archiver/cli/commands/tag.py` |   |   |   |   |   |   | (mark-dirty) |
| `src/chatgpt_library_archiver/__main__.py` | ✏️ |   |   |   |   |   |   |
| `src/chatgpt_library_archiver/management.py` (new) | ✨ |   |   |   |   |   |   |
| `src/chatgpt_library_archiver/affinity.py` (new) |   |   |   |   |   |   | ✨ |
| `src/chatgpt_library_archiver/metadata.py` | ✏️ |   |   |   |   |   | ✏️ |
| `src/chatgpt_library_archiver/tagger.py` |   | ✏️ |   |   |   |   | ✏️ |
| `src/chatgpt_library_archiver/tag_normalizer.py` |   |   |   |   |   |   | ✏️ |
| `src/chatgpt_library_archiver/importer.py` |   | ✏️ |   |   |   | ✏️ |   |
| `src/chatgpt_library_archiver/incremental_downloader.py` |   |   |   |   |   | ✏️ |   |
| `src/chatgpt_library_archiver/thumbnails.py` | ✏️ |   |   |   |   | ✏️ |   |
| `src/chatgpt_library_archiver/gallery.py` |   |   |   |   |   |   | ✏️ |
| `src/chatgpt_library_archiver/gallery_index.html` |   |   | ✏️ | ✏️ | ✏️ |   | ✏️ |
| `tests/test_cli.py` | ✏️ |   |   |   |   |   |   |
| `tests/test_management.py` (new) | ✨ |   |   |   |   |   |   |
| `tests/test_tagger.py` |   | ✏️ |   |   |   |   |   |
| `tests/test_importer.py` |   | ✏️ |   |   |   | ✏️ |   |
| `tests/test_thumbnails.py` |   |   |   |   |   | ✏️ |   |
| `tests/test_gallery.py` |   |   | ✏️ | ✏️ | ✏️ |   | ✏️ |
| `tests/test_metadata.py` |   |   |   |   |   |   | ✏️ |
| `tests/test_affinity.py` (new) |   |   |   |   |   |   | ✨ |
| `tests/test_end_to_end.py` |   |   |   |   |   | ✏️ |   |
| `README.md` | ✏️ |   |   |   |   |   | ✏️ |
| `CHANGELOG.md` | ✏️ | ✏️ | ✏️ | ✏️ | ✏️ | ✏️ | ✏️ |
| `docs/adr/0001-tag-affinity-sort.md` (new) |   |   |   |   |   |   | ✨ |
| `docs/adr/0002-full-resolution-lightbox.md` (new) |   |   | ✨ |   |   |   |   |
| `docs/adr/0003-gallery-management-cli.md` (new) | ✨ |   |   |   |   |   |   |

### Conflict Hotspots

- **`gallery_index.html`** — touched by tasks 3, 4, 5, 7. Land 4 (pinch fix, smallest, viewer-only) first to keep diffs reviewable, then 3 (Full mode), then 7 (sort option), then 5 (largest, mobile UX).
- **`metadata.py`** — tasks 1 and 7 both add helpers/fields. Land 7 first; task 1 then references the `affinity_index` field for sorting.
- **`thumbnails.py`** — tasks 1 (delete helper) and 6 (pool) both modify. Land 6 first; task 1's `delete_thumbnails` is additive.
- **`tagger.py` / `importer.py`** — tasks 2, 6, 7 all touch. Land 2 first (tiny, surgical), then 6 (refactor uses post-2 code), then 7 (additive sentinel write).

---

## Recommended Implementation Order

1. **Task 2 — Tag merge bug fix** (smallest, highest user value, unblocks confidence in tag tests).
2. **Task 4 — Pinch close fix** (small, viewer-only HTML diff; lands the pointer-event scaffolding before Tasks 3/5 touch the same area).
3. **Task 6 — Thumbnail pool** (purely additive; refactors `importer` and `incremental_downloader` while no other task touches them).
4. **Task 3 — Full-resolution lightbox** (small HTML/JS diff; depends on no other task).
5. **Task 5 — Mobile hover modal** (largest HTML/JS diff; lands after pinch fix to inherit pointer plumbing).
6. **Task 7 — Tag affinity sort** (adds metadata field + algorithm; needs to be in before Task 1's `gallery query --sort=affinity`).
7. **Task 1 — Gallery management CLI** (largest, depends on Task 7's `affinity_index`, Task 6's `delete_thumbnails` plumbing, Task 2's tag merge for correct `gallery tag --add` semantics).

---

## ADR Recommendations

| ADR | Justification |
| --- | --- |
| `0001-tag-affinity-sort.md` | Algorithm choice (Jaccard-greedy NN) + precompute decision + scalability fallback. Multi-module impact. |
| `0002-full-resolution-lightbox.md` | Decision to *not* introduce an xlarge thumbnail tier. Minor but durable; people will ask why we don't have a 2048 px tier. |
| `0003-gallery-management-cli.md` | New CLI verb namespace + sub-grouping convention; sets the pattern for future commands. |

No ADRs needed for tasks 2, 4, 5, 6 (bug fixes and incremental refactors).

---

## Risks and Open Questions

1. **Touch UX testing in CI** — we have no Playwright harness for the gallery. Tasks 3/4/5 will rely on HTML sentinel tests + manual smoke tests. Recommend opening a follow-up to add a Playwright job (out of scope here).
2. **`spawn` vs `fork` parity for thumbnail pool** — macOS defaults to `spawn` since Python 3.8. The existing `regenerate_thumbnails` already handles this; reuse the same context so we don't regress.
3. **Affinity dirty-check fingerprint** — choosing the right hash basis is subtle. Open question: should the fingerprint include item IDs (so adding a new tagless item is "no-op") or just the multiset of tag-sets? Decided in the ADR: fingerprint = sha256 of `sorted([(id, tuple(sorted(tags))) for ...])` — both sensitive to additions and to tag changes.
4. **Backwards compatibility of `gallery` command** — `gallery` (no subverb) currently regenerates. After Task 1 it must alias to `gallery build`. Verify in CI that scripts calling `chatgpt-library-archiver gallery` still work (test exists; extend it).
5. **Pinch + click suppression on iOS Safari** — the `click` after `touchend` cascade is fragile. Open question: is `pointercancel` reliably emitted on multi-touch in iOS 17/18 Safari? If not, we may need a 300 ms grace timer to suppress the trailing `click`. Validate with a real device before merging Task 4.
6. **Long-press on iOS** — system-level long-press (image save / context menu) competes with our handler. CSS `-webkit-touch-callout: none;` is the standard mitigation but disables save-image. We accept that; users have the existing "Raw file" link in the lightbox.
7. **Affinity sort + filtering** — when filters narrow the set, the precomputed `affinity_index` is a stable global ordering, not optimal for the filtered subset. The sort still places similar items adjacent within the subset (because relative order is preserved). Document this as expected behavior.
8. **`gallery rm` data loss** — destructive. Always confirm unless `-y`. Document loudly in README. Consider adding `gallery trash` (move to `gallery/.trash/`) as a future safer alternative — out of scope here, but call it out.

---

## Test Coverage Targets

The repo enforces ≥85% coverage. New modules:

- `affinity.py` — target 95% (small, pure-function module).
- `management.py` — target 90% (heavy CLI surface; integration tests cover the dispatch).

Existing modules touched: maintain or improve coverage.

---

End of plan.
