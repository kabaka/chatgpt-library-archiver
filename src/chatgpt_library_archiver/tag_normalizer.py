"""Tag normalization and consolidation for gallery metadata."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .metadata import GalleryItem, load_gallery_items, save_gallery_items
from .tagger import normalize_tag

# Threshold for fuzzy matching via SequenceMatcher.
_FUZZY_THRESHOLD = 0.85

# Maximum tag count to consider for pairwise fuzzy comparison.  Beyond this
# limit the quadratic cost becomes impractical.
_FUZZY_MAX_TAGS = 5000


@dataclass(slots=True)
class TagGroup:
    """A cluster of near-duplicate tags with a suggested canonical form."""

    canonical: str
    variants: list[str]
    count_by_tag: dict[str, int] = field(default_factory=dict)
    confidence: str = "high"

    @property
    def total_count(self) -> int:
        return sum(self.count_by_tag.values())


# ------------------------------------------------------------------
# 1. normalize_all_tags - safe batch normalizer
# ------------------------------------------------------------------


def normalize_all_tags(
    gallery_root: str = "gallery",
    *,
    dry_run: bool = False,
) -> int:
    """Re-normalize every tag across all gallery items.

    Returns the number of items whose tag list was modified.
    """
    items = load_gallery_items(gallery_root)
    modified = _normalize_items(items)
    if modified and not dry_run:
        save_gallery_items(gallery_root, items)
    return modified


def _normalize_items(items: list[GalleryItem]) -> int:
    """Apply ``normalize_tag`` to every tag in *items* in-place."""
    modified = 0
    for item in items:
        new_tags: list[str] = []
        seen: set[str] = set()
        for raw in item.tags:
            tag = normalize_tag(raw)
            if tag and tag not in seen:
                seen.add(tag)
                new_tags.append(tag)
        if new_tags != item.tags:
            item.tags = new_tags
            modified += 1
    return modified


# ------------------------------------------------------------------
# 2. find_similar_groups - clustering
# ------------------------------------------------------------------


def _count_tags(items: list[GalleryItem]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in items:
        for tag in item.tags:
            counter[tag] += 1
    return counter


def _plural_forms(tag: str) -> list[str]:
    """Return simple plural variants of *tag*."""
    forms = [tag + "s"]
    if tag.endswith("y"):
        forms.append(tag[:-1] + "ies")
    forms.append(tag + "es")
    return forms


def find_similar_groups(
    gallery_root: str = "gallery",
    *,
    items: list[GalleryItem] | None = None,
) -> list[TagGroup]:
    """Find clusters of near-duplicate tags.

    Returns a list of :class:`TagGroup` sorted by total occurrence count
    (most impactful first).
    """
    if items is None:
        items = load_gallery_items(gallery_root)

    counts = _count_tags(items)
    if not counts:
        return []

    merged: dict[str, set[str]] = {}  # canonical → set of variants
    assigned: dict[str, str] = {}  # variant → canonical
    confidence_map: dict[str, str] = {}  # canonical → confidence

    # --- pass 1: singular / plural --------------------------------
    for tag in sorted(counts, key=lambda t: -counts[t]):
        if tag in assigned:
            continue
        for plural in _plural_forms(tag):
            if plural in counts and plural not in assigned and plural != tag:
                # Pick the more frequent form as canonical.
                if counts[tag] >= counts[plural]:
                    canon, variant = tag, plural
                else:
                    canon, variant = plural, tag
                if canon not in merged:
                    merged[canon] = set()
                    confidence_map[canon] = "high"
                merged[canon].add(variant)
                assigned[variant] = canon
                assigned.setdefault(canon, canon)

    # --- pass 2: fuzzy matching -----------------------------------
    all_tags = sorted(counts, key=lambda t: -counts[t])
    if len(all_tags) <= _FUZZY_MAX_TAGS:
        for i, tag_a in enumerate(all_tags):
            canon_a = assigned.get(tag_a, tag_a)
            for tag_b in all_tags[i + 1 :]:
                if tag_b in assigned:
                    continue
                ratio = SequenceMatcher(None, tag_a, tag_b).ratio()
                if ratio >= _FUZZY_THRESHOLD:
                    canon = canon_a if canon_a in merged else tag_a
                    if canon not in merged:
                        merged[canon] = set()
                    if confidence_map.get(canon) != "high":
                        confidence_map[canon] = "medium"
                    merged[canon].add(tag_b)
                    assigned[tag_b] = canon

    # --- build TagGroup list --------------------------------------
    groups: list[TagGroup] = []
    for canon, variants in merged.items():
        all_members = {canon} | variants
        count_by_tag = {t: counts.get(t, 0) for t in sorted(all_members)}
        groups.append(
            TagGroup(
                canonical=canon,
                variants=sorted(variants),
                count_by_tag=count_by_tag,
                confidence=confidence_map.get(canon, "medium"),
            )
        )

    groups.sort(key=lambda g: -g.total_count)
    return groups


# ------------------------------------------------------------------
# 3. apply_consolidation - merge tags in metadata
# ------------------------------------------------------------------


def apply_consolidation(
    items: list[GalleryItem],
    merges: list[tuple[str, list[str]]],
) -> int:
    """Apply tag merges to *items* in-place.

    *merges* is a list of ``(canonical_tag, [variant_tags …])`` tuples.

    Returns the number of items whose tag list was modified.
    """
    # Build a quick replacement map: variant → canonical
    remap: dict[str, str] = {}
    for canonical, variants in merges:
        for v in variants:
            remap[v] = canonical

    if not remap:
        return 0

    modified = 0
    for item in items:
        new_tags: list[str] = []
        seen: set[str] = set()
        changed = False
        for tag in item.tags:
            replacement = remap.get(tag, tag)
            if replacement != tag:
                changed = True
            if replacement not in seen:
                seen.add(replacement)
                new_tags.append(replacement)
            elif replacement != tag:
                # The canonical already appeared - this is a dup removal.
                changed = True
        if changed:
            item.tags = new_tags
            modified += 1
    return modified


# ------------------------------------------------------------------
# 4. consolidate_tags - orchestrator
# ------------------------------------------------------------------


def _format_group(group: TagGroup) -> str:
    """Return a human-readable summary of a :class:`TagGroup`."""
    lines: list[str] = []
    lines.append(
        f"  canonical: {group.canonical!r} "
        f"(total: {group.total_count}, confidence: {group.confidence})"
    )
    for tag, count in sorted(group.count_by_tag.items(), key=lambda kv: -kv[1]):
        marker = " <-- canonical" if tag == group.canonical else ""
        lines.append(f"    {tag!r}: {count}{marker}")
    return "\n".join(lines)


def consolidate_tags(
    gallery_root: str = "gallery",
    *,
    auto_apply: bool = False,
    interactive: bool = True,
    dry_run: bool = False,
    printer: Callable[..., None] | None = None,
    prompter: Callable[[str], str] | None = None,
) -> int:
    """Normalize and optionally consolidate near-duplicate tags.

    Parameters
    ----------
    gallery_root:
        Path to the gallery directory.
    auto_apply:
        Automatically apply high-confidence merges without prompting.
    interactive:
        Prompt the user for medium-confidence merges.
    dry_run:
        Print a report without modifying metadata.
    printer:
        Callable used for output (defaults to :func:`print`).
    prompter:
        Callable used for interactive prompts (defaults to :func:`input`).

    Returns the number of items modified.
    """
    _print: Callable[..., None] = printer or print
    _prompt: Callable[[str], str] = prompter or input

    # Step 1 — always-safe normalization
    items = load_gallery_items(gallery_root)
    norm_count = _normalize_items(items)
    if norm_count:
        _print(f"Normalized tags on {norm_count} item(s).")

    # Step 2 — find similar groups
    groups = find_similar_groups(gallery_root, items=items)
    if not groups:
        _print("No near-duplicate tag groups found.")
        if norm_count and not dry_run:
            save_gallery_items(gallery_root, items)
        return norm_count

    _print(f"\nFound {len(groups)} near-duplicate tag group(s):\n")

    merges: list[tuple[str, list[str]]] = []

    for group in groups:
        _print(_format_group(group))

        if dry_run:
            continue

        if group.confidence == "high" and auto_apply:
            merges.append((group.canonical, group.variants))
            _print("  -> auto-applied (high confidence)\n")
        elif interactive:
            answer = (
                _prompt(f"  Merge into {group.canonical!r}? [Y/n] ").strip().lower()
            )
            if answer in ("", "y", "yes"):
                merges.append((group.canonical, group.variants))
                _print("  -> merged\n")
            else:
                _print("  -> skipped\n")
        elif group.confidence == "high" and not auto_apply:
            # Non-interactive, non-auto: skip
            _print("  -> skipped (use --auto to apply)\n")
        else:
            _print("  -> skipped (medium confidence, use interactive mode)\n")

    merge_count = 0
    if merges and not dry_run:
        merge_count = apply_consolidation(items, merges)
        _print(f"\nConsolidated tags on {merge_count} item(s).")

    total_modified = norm_count + merge_count
    if total_modified and not dry_run:
        save_gallery_items(gallery_root, items)

    if dry_run:
        _print("\nDry run — no changes were written.")

    return total_modified
