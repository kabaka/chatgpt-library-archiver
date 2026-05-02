"""Tag-affinity ordering for gallery items.

Computes an integer ``affinity_index`` on each :class:`GalleryItem` such that
items with overlapping tag sets are placed adjacent to one another. The
algorithm is a greedy nearest-neighbor traversal over Jaccard similarity,
seeded from the densest tag cluster (the item belonging to the most-frequent
global tag, with the largest tag set as a tiebreaker).

Items with no tags receive ``affinity_index = None`` and are intended to be
sorted to the end of the gallery view.

The module is dependency-free pure Python; see
``docs/adr/0001-affinity-sort-algorithm.md`` for the design rationale.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from .metadata import GalleryItem, created_at_sort_key


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if intersection == 0:
        return 0.0
    union = len(a) + len(b) - intersection
    return intersection / union


def _seed_index(
    tag_sets: list[frozenset[str]],
    ids: list[str],
    candidates: list[int],
) -> int:
    """Pick the seed: item belonging to the globally most-frequent tag.

    Tiebreakers (in order):
      1. Largest tag-set cardinality.
      2. Lexicographic id (deterministic).
    """
    counts: Counter[str] = Counter()
    for idx in candidates:
        counts.update(tag_sets[idx])

    # Determine the most frequent tag deterministically (highest count, then
    # lexicographic tag name).
    most_common_tag = min(
        counts.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )[0]

    # Among candidates containing that tag, pick the one with the largest
    # tag set (then lexicographic id).
    return min(
        (idx for idx in candidates if most_common_tag in tag_sets[idx]),
        key=lambda idx: (-len(tag_sets[idx]), ids[idx]),
    )


def compute_affinity_indices(items: Iterable[GalleryItem]) -> None:
    """Assign ``affinity_index`` to each item in ``items`` in place.

    Items with empty tag lists receive ``affinity_index = None``. The
    remaining items are ordered via greedy nearest-neighbor traversal over
    Jaccard similarity and assigned a contiguous 0-based index in traversal
    order.

    The computation is deterministic: for the same input (regardless of the
    iteration order of the supplied iterable) the resulting indices are
    stable.
    """
    items_list = list(items)
    if not items_list:
        return

    tagged_indices: list[int] = []
    for i, item in enumerate(items_list):
        if item.tags:
            tagged_indices.append(i)
        else:
            item.affinity_index = None

    if not tagged_indices:
        return

    # Build deterministic, normalized tag sets and ids for comparison.
    tag_sets: list[frozenset[str]] = [frozenset() for _ in items_list]
    ids: list[str] = [item.id for item in items_list]
    for idx in tagged_indices:
        tag_sets[idx] = frozenset(items_list[idx].tags)

    seed = _seed_index(tag_sets, ids, tagged_indices)

    visited: set[int] = {seed}
    order: list[int] = [seed]
    current = seed
    remaining = set(tagged_indices) - visited

    while remaining:
        current_set = tag_sets[current]
        # Score each candidate; tiebreakers: shared-tag count (desc),
        # created_at (desc -> newer first), then lexicographic id.
        best_idx = min(
            remaining,
            key=lambda idx: (
                -_jaccard(current_set, tag_sets[idx]),
                -len(current_set & tag_sets[idx]),
                -created_at_sort_key(items_list[idx].created_at),
                ids[idx],
            ),
        )
        order.append(best_idx)
        visited.add(best_idx)
        remaining.remove(best_idx)
        current = best_idx

    for position, idx in enumerate(order):
        items_list[idx].affinity_index = position
