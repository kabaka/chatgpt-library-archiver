# Peer Review — Feature Batch Implementation Plan (2026-05-01)

**Reviewed file:** [docs/reviews/2026-05-01-feature-batch/PLAN.md](docs/reviews/2026-05-01-feature-batch/PLAN.md)
**Reviewer:** readiness-reviewer
**Date:** 2026-05-02

## Verdict

**APPROVED-WITH-CHANGES**

The plan is thorough, well-structured, and the technical approaches are
generally sound. No blockers found. However, several issues need to be
addressed before implementation begins: (a) two completeness gaps in the
gallery-management CLI surface (filename rename/move, model filter), (b) a
likely-incorrect `touch-action` value, (c) several stale cited line numbers,
and (d) a missing schema/back-compat note for the new `affinity_index` field.

---

## Issues

### Major

- **[major] Task 1 — missing `rename` / `move` subcommand.**
  The user-facing review brief explicitly enumerates "rename/move" as a use
  case. The plan covers `set` for string fields and `rm` for deletion, but
  there is no subcommand to rename `images/<filename>` and update all
  thumbnails + metadata atomically. Renaming the on-disk filename touches
  three places (image file, thumbnail files in `thumbs/{small,medium,large}/`,
  and `GalleryItem.filename` + `thumbnails` + `thumbnail`). Either add
  `gallery mv ID NEW-NAME` (or `gallery rename`) to the surface in
  [PLAN.md](docs/reviews/2026-05-01-feature-batch/PLAN.md) §"New Subcommand
  Surface", or explicitly justify omitting it.

- **[major] Task 1 — `query --by-model` not addressable.**
  The brief lists "model" as a query criterion, but `GalleryItem` in
  [metadata.py](src/chatgpt_library_archiver/metadata.py#L77) has no `model`
  field; it is at best an unstructured key in `GalleryItem.extra`. The plan
  silently omits a model filter without acknowledging the schema gap. Either
  (a) add a `--extra KEY=VALUE` generic filter in `query` to cover model and
  any future ad-hoc fields, or (b) call out explicitly in the plan that
  per-model filtering is out of scope until model is promoted to a
  first-class field.

- **[major] Task 4 — `touch-action: pinch-zoom` likely too restrictive.**
  Plan §Task 4 specifies `#viewer { touch-action: pinch-zoom; }`. Per the
  CSS Touch Action spec, `pinch-zoom` alone disables `pan-x`/`pan-y`, so
  after the user pinches the image they cannot pan around the zoomed view —
  a worse UX than today. The intended value is almost certainly
  `touch-action: manipulation` (allows pinch + pan, blocks double-tap zoom)
  or the explicit `pan-x pan-y pinch-zoom`. Validate on iOS Safari before
  implementation; document the chosen value in the plan.

### Minor

- **[minor] Cited line numbers are stale across the plan.**
  Spot-checked references vs. current source:
  - `tagger.py#L208` for `item.tags = tags` → actual line **219**
    ([tagger.py](src/chatgpt_library_archiver/tagger.py#L219)).
  - `tagger.py#L122` for `normalize_tag` → actual line **126**.
  - `metadata.py#L24` for `normalize_created_at` → actual line **22**.
  - `metadata.py#L207` for `save_gallery_items` → actual line **206**.
  - `incremental_downloader.py#L31` for `_sanitize_id` → actual line **32**.
  - `incremental_downloader.py#L100` for the `MAX_BYTES` limit → the actual
    `max_bytes=100 * 1024 * 1024` argument is at line **106**, and there is
    no `MAX_BYTES` module-level constant (the value is inlined). The plan
    implies a named constant exists.
  - `thumbnails.py#L226` for `create_thumbnails` → actual line **231**.
  - `thumbnails.py#L98` for `thumbnail_relative_paths` → actual line
    **101** (and the function is named `thumbnail_relative_paths`, not
    `thumbnail_relative_path`; the plan uses both spellings).
  - `gallery_index.html#L1010` for `#viewerImg` → element declared at
    **523**; the JS reference is at **999**.
  - `gallery_index.html#L1118` for the `touchstart` listener → actual line
    **1119**.
  None are individually blocking, but together they suggest the plan was
  drafted against an earlier checkout. Refresh all `#L…` references before
  starting implementation so file-link reviews stay trustworthy.

- **[minor] Task 3 framing vs. reality.**
  The executive summary calls Task 3 "full-resolution lightbox", but §Task 3
  itself correctly identifies the bug as being in `gallery-full` *list mode*
  and explicitly notes the lightbox already loads `item.src`. This is
  accurate and well-analyzed, but the title in the exec summary will mislead
  reviewers and CHANGELOG readers. Rename the task and the CHANGELOG entry
  to "Full-resolution images in `gallery-full` mode" (or similar) so the
  scope is unambiguous.

- **[minor] Task 7 — `affinity_index` schema back-compat not addressed.**
  Adding `affinity_index: int | None = None` to `GalleryItem` is
  forward-compatible (old metadata simply loads with `None`). However, the
  plan should call out the **reverse** direction: a user who downgrades
  after running `gallery build` will have an unrecognized key. Looking at
  [metadata.py:104-128](src/chatgpt_library_archiver/metadata.py#L104), the
  current `from_dict` keeps unknown keys in `extra`, so the value would
  round-trip even on older code — but only if `affinity_index` is *not*
  added to the explicit excluded-keys set on the older branch. Document
  this and verify the round-trip in `tests/test_metadata.py` so we don't
  regress the `extra` preservation contract.

- **[minor] Task 6 — pool shutdown on interrupted runs.**
  §Task 6 says "Created lazily on first thumbnail submission, closed in
  `finally`". The plan does not address what happens if the user `Ctrl+C`s
  mid-run: the existing `regenerate_thumbnails` uses a context-managed
  `ProcessPoolExecutor` that joins workers on `__exit__`, which can hang
  several seconds on macOS spawn. State explicitly that Ctrl+C produces a
  prompt shutdown (e.g., `executor.shutdown(wait=False, cancel_futures=True)`
  in the cleanup path) and add a test or manual smoke check to verify.

- **[minor] Task 7 — non-standard greedy seed.**
  §Task 7 picks the seed as "item with the most tags in the most-frequent
  global tag". This is unusual — typical greedy-NN seedings use either an
  arbitrary node or one with extremal degree. The choice is defensible
  (anchor in the densest cluster) but is also more sensitive to a single
  popular tag dominating the ordering. The proposed ADR
  `0001-tag-affinity-sort.md` should explicitly justify the seed choice and
  list rejected alternatives, including "seed at lowest-degree tagged item"
  and "seed deterministically by id".

- **[minor] Task 5 — `i` keyboard shortcut grows scope.**
  §Task 5 quietly adds "pressing `i` while a card is focused opens the
  modal". This is a new global keyboard binding that may collide with the
  search box (if focused, `i` should be a literal character). Either drop
  the binding from the plan, or specify the focus-guard logic and test it.

- **[minor] Test plan adequacy for UX tasks.**
  Tasks 3/4/5 rely on HTML sentinel tests + manual smoke. The plan
  acknowledges this in Risk #1, but does not commit to a follow-up issue or
  define what "manual smoke" means in a way that survives across
  contributors. Recommend (a) opening a tracking issue for the Playwright
  harness as part of this batch and referencing it in the plan, and (b)
  adding a short "Manual smoke checklist" subsection to each affected task
  so a future contributor can re-run it.

- **[minor] CLI alias regression risk.**
  Risk #4 mentions backward compatibility of bare `gallery` → `gallery
  build`. The plan does not specify *how* the alias is implemented in
  `argparse` nested subparsers (which do not natively dispatch a default
  child). Spell out the mechanism (likely `parser.set_defaults(gallery_verb
  ="build")` plus a manual `if args.gallery_verb is None: handle_build(args)`
  fallback) and add a test that `chatgpt-library-archiver gallery` (no
  verb) still rebuilds.

### Nits

- **[nit] §Task 1 — `set --field=value` is ambiguous.** Argparse
  conventionally uses `--field VALUE` and a `--field=value` form is
  shell-syntax, not separate option syntax. Clarify whether the verb is
  `gallery set ID --title "Foo"` (preferred) or some literal `--field=value`
  string parser.
- **[nit] §Task 1 — `gallery export` overlaps with `gallery query
  --format=json`.** Consider folding `export` into `query` and dropping the
  separate verb; otherwise document why they are distinct.
- **[nit] §Task 6 — `--thumbnail-workers` flag name.** Existing flag is
  `--max-workers` for download; `--tag-workers` for tagging. To stay
  consistent, prefer `--thumb-workers` (matches the dir name `thumbs`) or
  `--thumbnail-max-workers`.
- **[nit] Plan formatting.** The "Executive Summary (10 lines)" header
  declares 10 lines but the body has 10 numbered items plus a leading
  paragraph; either drop the line count from the header or trim.
- **[nit] §Task 2 references `tag_normalizer.py` indirectly.** The fix
  proposes calling `normalize_tag` from
  [tagger.py](src/chatgpt_library_archiver/tagger.py#L126) inside
  `ImportConfig.__post_init__`. There is also a separate
  [tag_normalizer.py](src/chatgpt_library_archiver/tag_normalizer.py)
  module — confirm we are using the right entry point and not introducing a
  duplicate normalization path.

---

## Suggested Edits to the Plan

1. **Add a `Task 1` subcommand** for filename rename:
   `gallery mv ID NEW-FILENAME` (renames image file, updates thumbnail
   filenames, mutates `filename`/`thumbnails`/`thumbnail` fields,
   path-traversal-safe). Update the §"New Subcommand Surface" table and
   §"Edge Cases".
2. **Add a generic `--extra KEY=VALUE` filter** to `gallery query` (or
   strike model-filtering from scope explicitly) so the brief's
   "query by model" requirement is addressed.
3. **Change `touch-action: pinch-zoom`** in §Task 4 to either
   `manipulation` or `pan-x pan-y pinch-zoom`; verify on real iOS Safari
   and document the chosen value.
4. **Refresh all cited `#L…` line numbers** against `main` HEAD before
   implementation begins.
5. **Rename Task 3** (and its CHANGELOG entry) to clarify the fix is for
   `gallery-full` list mode, not the lightbox.
6. **Add a back-compat round-trip test** for `affinity_index` in
   `tests/test_metadata.py` that verifies `extra`-key preservation when
   loading metadata generated by a newer version.
7. **Specify pool shutdown behavior** for Task 6 (Ctrl+C path,
   `cancel_futures=True`) and add a manual or automated check.
8. **Justify the greedy-NN seed choice** in `0001-tag-affinity-sort.md`
   with a list of rejected seed strategies.
9. **Drop or fully specify the `i` keyboard shortcut** in Task 5.
10. **Spell out the bare-`gallery` alias mechanism** under
    `argparse` nested subparsers in §Task 1, and add a regression test.
11. **Open a follow-up issue** for the Playwright harness referenced in
    Risk #1; link it in the plan.

---

## Strengths Worth Preserving

- File-touch matrix and merge-conflict analysis are thorough and the
  proposed implementation order does correctly minimize collisions in
  `gallery_index.html`, `metadata.py`, and `thumbnails.py`.
- ADR scoping (3 ADRs) is appropriate. Tasks 2/4/5/6 correctly defer to
  CHANGELOG only.
- Tag-merge bug fix (Task 2) is correctly diagnosed; the order-preserving
  dedupe and the upstream `normalize_tag` call in `ImportConfig.__post_init__`
  together address both the clobber and the case-mismatch dup.
- Affinity algorithm comparison table is clear; Jaccard greedy-NN at the
  documented scale (≤20k items) is a defensible choice and avoids heavy
  optional dependencies.
- Pointer Events migration in Task 4 is the right architectural call — it
  fixes the dual-listener inconsistency rather than papering over it.
- Risks section explicitly enumerates open questions (iOS pointer-cancel
  reliability, long-press iOS callout, affinity dirty-check fingerprint),
  which is exactly what we want from a plan.

---

End of review.
