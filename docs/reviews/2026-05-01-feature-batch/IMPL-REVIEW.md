# Implementation Review — 2026-05-01 Feature Batch

* Reviewer: readiness-reviewer (peer review pass)
* Date: 2026-05-02
* Scope: all uncommitted changes in working tree implementing the seven
  tasks defined in [PLAN.md](PLAN.md).
* Verification baseline already confirmed by the implementer:
  * `make test` — 410 passed, 88.66% coverage
  * `make lint` — clean
  * `pre-commit run --all-files` — clean

## Verdict

**APPROVED-WITH-CHANGES.**

No blockers. Tests, lint, and coverage gates are green; security posture is
intact (path-traversal guards present, symlinks refused, no shell
interpolation in CLI args, env var leak proactively fixed). The
implementations of the bug fixes (#2 tag merge, #4 pinch close) and the
algorithmic core of #6 (thumbnail pool) and #7 (affinity sort) match the
plan precisely and have strong test coverage.

The "with changes" caveat covers two clusters:

1. **Documentation gap**: CHANGELOG only records 1 of 7 tasks; README does
   not advertise three new user-visible features. Users will not see what
   shipped.
2. **Scope cuts in the management CLI (Task 1)**: `gallery query` is
   missing roughly half of the planned filter / sort / format options the
   plan specified, including the `--format=ids` mode that the plan
   documented as the entry point for `query | xargs gallery rm` pipelines,
   and the `--sort=affinity` mode that is the only CLI consumer of the new
   Task 7 field. `export` is missing filter sharing. `dedupe` is
   report-only.

None of these are correctness defects; they are deferred surface area.
Either close them in this batch or open a follow-up issue and explicitly
mark them deferred in the CHANGELOG.

## Counts

* **Blockers: 0**
* **Majors: 3** (CHANGELOG coverage, importer normalization gap, missing
  query CLI surface)
* **Minors: 10**
* **Nits: 4**

---

## Issues

### Major

**M1. CHANGELOG records only 1 of 7 tasks.**
*Severity: major. File: [CHANGELOG.md](../../../CHANGELOG.md)*

The plan required a CHANGELOG entry for every task. The diff adds the
"gallery management subcommands" entry plus an unrelated `--yes` env
restoration fix; nothing for tasks 2 (tag merge fix), 3 (full-resolution
in `gallery-full`), 4 (pinch-close fix), 5 (long-press metadata modal),
6 (parallel thumbnail pool + `--thumb-workers`), or 7 (tag affinity sort).
End users have no record that these shipped.

*Fix*: Add one bullet per task under the appropriate Added / Changed /
Fixed heading. Example skeleton:

```markdown
### Added
- Tag affinity sort mode in the gallery viewer (precomputed
  `affinity_index`, opt-in via the new "Tag similarity" sort option).
- `download` / `import` `--thumb-workers` flag controlling thumbnail
  ProcessPoolExecutor size (default `min(cpu_count, 8)`).

### Changed
- `gallery-full` mode now serves the original image at high DPI via
  `srcset` instead of the 400px `large` thumbnail.
- Long-press on touch devices opens a metadata modal; the `:hover`
  overlay is suppressed under `(hover: none) and (pointer: coarse)`.

### Fixed
- `tag --tag-new` no longer overwrites user-supplied tags; existing
  tags are merged with AI tags, deduplicated by normalized form, and
  order is preserved.
- Pinch-to-zoom in the lightbox no longer triggers `closeViewer()`
  (rewritten on Pointer Events with multi-touch latching).
```

---

**M2. Importer scope cut: `ImportConfig.__post_init__` does not normalize tags.**
*Severity: major. File: [src/chatgpt_library_archiver/importer.py](../../../src/chatgpt_library_archiver/importer.py#L67-L72)*

PLAN.md Task 2 explicitly requires:

> Today `importer.ImportConfig.__post_init__` splits comma-separated input
> but does not lowercase/normalize — Task 2 also adds a `normalize_tag` call
> there so user-supplied tags pass through the same canonicalization the AI
> tags use, preventing case-only duplicates.

The implementation only splits and strips. Mitigation exists in `tagger.py`
(the merge keys the seen-set on `normalize_tag`), but the user's literal
`"Sunset"` survives in `item.tags`, so downstream consumers that use the
raw value (affinity Jaccard sets, query `--tag` matching, statistics) see
case-sensitive duplicates with AI-generated `"sunset"`. The plan called
this out explicitly.

*Fix*:

```python
def __post_init__(self) -> None:
    """Normalize tags by splitting comma-separated values."""
    from .tagger import normalize_tag  # local import to avoid cycle
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in self.tags:
        for part in (p.strip() for p in tag.split(",")):
            if not part:
                continue
            canonical = normalize_tag(part)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            normalized.append(canonical)
    self.tags = normalized
```

Add a regression test in `tests/test_importer.py` asserting that
`ImportConfig(tags=["Sunset", "sunset"])` collapses to `["sunset"]`.

---

**M3. `gallery query` is missing roughly half the planned surface.**
*Severity: major. File: [src/chatgpt_library_archiver/cli/commands/gallery.py](../../../src/chatgpt_library_archiver/cli/commands/gallery.py#L181-L240)*

PLAN.md Task 1 lists these query options. Implemented vs. missing:

| Option | Status |
| --- | --- |
| `--id` / `--tag` / `--no-tag` / `--title-contains` / `--prompt-contains` / `--extra` / `--limit` | ✓ implemented |
| `--has-thumbnail` / `--missing-thumbnail` | ✓ (renamed from plan's `--missing-thumbs`) |
| `--has-tags` / `--no-tags` | ✗ missing |
| `--has-prompt` / `--no-prompt` | ✗ missing |
| `--conversation-id` | ✗ missing |
| `--missing-file` | ✗ missing |
| `--since YYYY-MM-DD` / `--until YYYY-MM-DD` | ✗ missing (only epoch-second `--created-after/-before` accepted) |
| `--sort=date\|title\|affinity` / `--reverse` | ✗ missing — *no CLI consumer of the new `affinity_index` field* |
| `--format=ids` (newline-delimited) | ✗ missing — breaks the documented `query | xargs gallery rm` pipeline |
| `format=table` (default) | partially — implemented as `plain` |

Two of these are particularly visible:

* `--sort=affinity` is the only CLI surface that lets users consume the
  Task 7 `affinity_index` outside the HTML viewer; without it Task 7's
  stated benefit ("a precomputed `affinity_index` field also lets external
  CLI tools (`gallery query --sort=affinity`) consume it") is undelivered.
* `--format=ids` is referenced verbatim in the plan as the pipeline glue
  for chaining `query` into `rm` / `tag` / `untag`. Without it, the CLI
  composability story breaks down.

*Fix*: implement at minimum `--sort` (date/title/affinity, with `--reverse`)
and `--format=ids`. The remaining boolean predicates (`--has-tags`,
`--no-tags`, `--has-prompt`, `--no-prompt`, `--conversation-id`,
`--missing-file`) are one-liner additions in `QueryFilters` and
`_matches`. Either ship them or open a follow-up issue and add a
`### Deferred` bullet to the CHANGELOG.

---

### Minor

**m1. `gallery rm` does not prompt; it refuses without `--yes`.**
*File: [src/chatgpt_library_archiver/cli/commands/gallery.py](../../../src/chatgpt_library_archiver/cli/commands/gallery.py#L413-L421)*

Plan said: "rm ... prompt unless root -y was passed". Implementation
prints "Refusing to delete N item(s) without --yes" and exits 1.
Refusing is *safer* than prompting but does not match the documented
behavior, and there is no interactive Y/N path. Either update the plan
or implement a prompt via `utils.prompt_yes_no` to honor PLAN intent.

---

**m2. README missing user-visible changes.**
*File: [README.md](../../../README.md)*

The new gallery management table was added, but the README does not
mention:

* `--thumb-workers` flag on `download` and `import`.
* The new "Tag similarity" sort option in the gallery viewer.
* Long-press metadata modal on touch devices (worth a sentence in the
  gallery section so iOS users know the affordance exists).

*Fix*: append three short lines/sentences to the appropriate Usage
subsections.

---

**m3. ADRs 0002 and 0003 not created.**
*Path: [docs/adr/](../../../docs/adr/)*

Plan recommended three ADRs; only `0001-affinity-sort-algorithm.md`
shipped (and is excellent — covers all four rejected seed strategies and
all five rejected algorithms). The plan explicitly recommended:

* `0002-full-resolution-lightbox.md` — rationale for *not* adding an
  `xlarge` thumbnail tier in Task 3. Real durable design knowledge that
  future contributors will ask about.
* `0003-gallery-management-cli.md` — verb-based dispatch design and the
  bare-`gallery` aliasing trick for Task 1.

The plan's wording is "recommended", not "required", so this is a
minor. Recommend writing both as short MADRs; each can be ≤80 lines.

---

**m4. Affinity dirty-check / cache fingerprint not implemented.**
*Files: [src/chatgpt_library_archiver/affinity.py](../../../src/chatgpt_library_archiver/affinity.py), [src/chatgpt_library_archiver/gallery.py](../../../src/chatgpt_library_archiver/gallery.py#L56)*

Plan called for `gallery/.affinity-cache` JSON sentinel storing a
sha256 fingerprint of `sorted([(id, tuple(sorted(tags))) for ...])` so
recompute is opportunistic. Implementation always recomputes during
`gallery build`. At ≤20k items this is fast (well under 1s) and
acceptable, but at the documented ceiling (50k) the unconditional
recompute starts to be visible. Recommend deferring to a follow-up if
not addressed in this batch.

---

**m5. Affinity 50k bucket-fallback not implemented.**
*File: [src/chatgpt_library_archiver/affinity.py](../../../src/chatgpt_library_archiver/affinity.py)*

Plan documented:

> Large galleries (>50k items): document a fallback to bucket-sort by
> primary tag if N exceeds a threshold

Not implemented. The ADR notes the ceiling but doesn't add the guard.
Acceptable since no real user will hit 50k, but plan said to add the
fallback.

---

**m6. `gallery export` does not honor query filters and lacks `--format=tsv`.**
*File: [src/chatgpt_library_archiver/cli/commands/gallery.py](../../../src/chatgpt_library_archiver/cli/commands/gallery.py#L507-L522)*

Plan: "`gallery export [--format=json|csv|tsv]` — Stream filtered
results in machine-readable form" and "shared with `query`". The
implementation always exports every item and supports only json/csv.
Result: there is no way to produce filtered CSV output today.

*Fix*: register `_add_query_filter_args(p)` on the export parser; pass
the same `_build_filters` result through `query_items`; add `tsv` to
the `--format` choices (one extra branch in `_handle_export`).

---

**m7. `gallery dedupe` lacks `--delete` and `--rehash`.**
*File: [src/chatgpt_library_archiver/cli/commands/gallery.py](../../../src/chatgpt_library_archiver/cli/commands/gallery.py#L541-L559)*

Plan listed both flags. Report-only is delivered. Acceptable as a
deferred enhancement.

---

**m8. `rename_item` rollback failures swallowed silently.**
*File: [src/chatgpt_library_archiver/management.py](../../../src/chatgpt_library_archiver/management.py#L535-L538)*

Plan: "If even the rollback fails (extremely rare — disk full
mid-operation), log every still-renamed pair to stderr so the operator
can recover manually." Implementation:

```python
except OSError:
    for src, dst in reversed(completed):
        with contextlib.suppress(OSError):
            dst.rename(src)
    raise
```

The `contextlib.suppress(OSError)` swallows rollback failures with no
record. If a real disk-full mid-operation occurs the operator has no
way to find the orphaned renames.

*Fix*: replace with explicit `try/except` that writes
`f"WARNING: rollback failed for {dst} -> {src}: {exc}"` to stderr (or
use `logging`).

---

**m9. `rename_item` updates thumbnail rels via `str.replace` on the full path.**
*File: [src/chatgpt_library_archiver/management.py](../../../src/chatgpt_library_archiver/management.py#L548-L555)*

```python
for size, rel in item.thumbnails.items():
    new_thumbs[size] = rel.replace(old_filename, new_filename).replace(
        f"{Path(old_filename).stem}.webp", f"{new_stem}.webp"
    )
```

Fragile. If `old_filename` happens to be a substring elsewhere in the
rel (unlikely under the current `thumbs/<size>/<file>` layout, but the
helper takes no defensive precaution), the wrong segment may be
rewritten. Also runs the second replace unconditionally even when the
thumb is not webp.

*Fix*: rebuild the rel path from its known structure
(`f"{THUMBNAIL_DIR_NAME}/{size}/{new_basename}"`) using the actual
extension of the old rel.

---

**m10. `--yes` env restoration covers only `os.environ.pop` correctness; tests pass but the contract should be documented.**
*File: [src/chatgpt_library_archiver/__main__.py](../../../src/chatgpt_library_archiver/__main__.py#L36-L52)*

The fix is correct. The only nit is that the CHANGELOG should explain
*why* this was needed (it's a real bug if `main()` is called from a
host process or from tests that import `main`).

---

### Nits

**n1. `longPressFired` flag may persist across gestures on platforms without synthetic click.**
*File: [src/chatgpt_library_archiver/gallery_index.html](../../../src/chatgpt_library_archiver/gallery_index.html) (long-press click suppressor)*

`longPressFired = true` is reset only inside the gallery-container
`click` capture handler. If the timer fires but no synthetic click
follows (e.g., desktop browser DevTools emulator releasing the pointer
without a trailing `click`), the flag persists and the next unrelated
tap is swallowed. Real-world impact on iOS / Android touch hardware is
negligible (the synthetic click always follows pointerup), but a stale
guard could surprise emulator-based testing.

*Fix*: also reset `longPressFired` inside `pointerup` after a short
delay (e.g. `setTimeout(() => { longPressFired = false; }, 350)`),
or reset it whenever `openMetaModal` returns.

---

**n2. `ThumbnailPool.submit` calls `reporter.add_total(1)` on a shared StatusReporter.**
*File: [src/chatgpt_library_archiver/thumbnails.py](../../../src/chatgpt_library_archiver/thumbnails.py#L583-L586)*

The importer passes its `"Importing images"` reporter (initialized with
`total=len(items)`) into the pool. Each thumbnail submission grows the
total by 1 and each completion calls `advance()`. Net effect: the
progress bar's denominator drifts upward as thumbnails enqueue, which
is mostly harmless but visibly inconsistent with the "Importing images"
label. Cosmetic.

*Fix*: either give the pool its own private reporter (separate progress
line) or omit the per-thumbnail accounting when reporter ownership is
external.

---

**n3. `gallery affinity` saves directly via `save_gallery_items` while every other mutating verb routes through `_save` (which itself recomputes affinity).**
*File: [src/chatgpt_library_archiver/cli/commands/gallery.py](../../../src/chatgpt_library_archiver/cli/commands/gallery.py#L532-L538)*

This is correct (it would be wasted work to recompute twice) but the
asymmetry is confusing. A one-line comment in `_handle_affinity`
explaining "skip `_save` to avoid double recompute" would help future
maintainers.

---

**n4. `find_duplicates` reports both filename and checksum collisions, but plan said checksum only.**
*File: [src/chatgpt_library_archiver/management.py](../../../src/chatgpt_library_archiver/management.py#L640-L676)*

Minor scope creep. Filename duplicates *should* be impossible given
the importer's collision avoidance, so reporting them is defensive but
unrequested. Either keep with a brief comment or drop the filename
branch.

---

## Cross-check vs. plan, per task

| Task | Plan match | Notes |
| --- | --- | --- |
| 1 — Gallery management subcommands | partial | Verbs `tag`, `untag`, `set`, `unset`, `mv`, `rm`, `stats`, `query`, `show`, `export`, `affinity`, `dedupe`, `verify`, `prune-thumbs`, `build` all present and dispatched correctly via `gallery_handler`. Bare-`gallery` alias verified. **Cuts**: M3 (query options), m1 (rm prompt), m6 (export filters/tsv), m7 (dedupe flags). |
| 2 — Tag merge bug fix | mostly match | Tagger merge is correct: existing-first, dedup via `normalize_tag` keyed seen-set, AI tags appended. Comprehensive tests in `test_tagger.py` (lines 353–425). **Gap**: M2 (importer normalization). |
| 3 — Full-resolution `gallery-full` | match | `sizeKeyToWidth.full = 2400` ✓; `srcsetForKey` appends original at 2400w when sizeKey === 'full' ✓; `updateThumbnailsForSize('full')` forces `nextSrc = img.dataset.full` ✓. |
| 4 — Pinch-close fix | match | Pointer Events with `activePointers` Map, `wasMultiTouch` latch, `pointercancel` sets latch, `touch-action: manipulation` on `#viewer img`, synthetic-click suppression. Mouse swipe correctly excluded via `e.pointerType !== 'mouse'`. |
| 5 — Long-press modal | match | Modal markup present; `(hover: none) and (pointer: coarse)` gate in both CSS (line 113) and JS (`coarsePointerMQ.matches`); 500ms timer with 10px movement threshold; click suppression via capture-phase listener. **Nit**: n1. |
| 6 — Thumbnail pool | match | `ThumbnailPool` lazy-starts, `default_thumbnail_workers() = min(cpu_count, 8)`, `__exit__` calls `shutdown(wait=False, cancel_futures=True)` on `KeyboardInterrupt`. Test `test_create_thumbnails_pool_shutdown_on_interrupt` asserts cancel_futures behavior. `--thumb-workers` flag on both download and import. **Nit**: n2 (shared reporter). |
| 7 — Tag affinity sort | match | Jaccard greedy-NN, densest-cluster seed with documented tiebreakers (count desc → lex tag, then tagset size → lex id), deterministic. Round-trips through `from_dict`/`to_dict` and excluded from `extra` correctly. JS comparator handles `null` per spec. ADR 0001 thoroughly documents rejected alternatives. **Cuts**: m4 (no dirty-check cache), m5 (no >50k fallback). |

## Security spot-check

Clean.

* Path traversal: `_safe_image_path` rejects `/`, `\`, `.`, `..` and
  uses `is_relative_to` after `resolve()`. `_check_rename_target`
  applies the same gate plus collision detection.
* Symlink avoidance: `remove_items` refuses to delete symlinked
  images and reports an error.
* No shell interpolation: all CLI args go through argparse and are
  passed as Python objects; no `subprocess` / `shell=True` introduced.
* No new secrets logging or env-var exfiltration.
* `--yes` env restoration in `__main__.py` is implemented correctly
  with a try/finally guard.
* HTML modal injects `textContent` only (no `innerHTML` for
  user-controlled strings); `safeHref` is reused for the
  `conversation_link` URL. Tag pill `pill.textContent = tag` is safe.

## Sloppy code / dead code / TODOs

None found. No `TODO`, `FIXME`, `XXX`, `print(` debug statements, or
stray commented-out blocks in the new modules.

## Test coverage spot-check

* `test_affinity.py` covers determinism, empty input, single-item,
  all-disjoint, three-cluster grouping. ✓
* `test_thumbnails.py` adds pool tests including the
  `KeyboardInterrupt` / `cancel_futures=True` assertion the plan
  required. ✓
* `test_metadata.py` covers `affinity_index` round-trip and
  unknown-key preservation in `extra`. ✓
* `test_tagger.py` covers all five merge branches the plan called
  out (existing-only, AI-only, combined order, case dedup, empty
  existing). ✓
* `test_gallery.py` HTML sentinels assert the new sort option,
  modal markup, and pointer listeners. ✓
* `test_gallery_commands.py` (604 lines) covers the new CLI surface
  including bare-`gallery` alias, `mv` rollback, `rm` confirmation
  gating. ✓

Coverage 88.66% > the 85% gate.

## Summary of recommended actions

Before merge:

1. **(M1)** Add CHANGELOG bullets for tasks 2–7.
2. **(M2)** Add `normalize_tag` to `ImportConfig.__post_init__`
   (plus the regression test).
3. **(M3)** Either implement at least `gallery query --sort=affinity`
   and `--format=ids` (the two highest-leverage cuts), or add an
   explicit "Deferred" CHANGELOG section listing them and open a
   follow-up issue.

Recommended but optional:

4. README updates (m2).
5. ADRs 0002 + 0003 (m3).
6. `rename_item` rollback logging (m8) and rel rebuild (m9).

Cosmetic:

7. n1–n4.
