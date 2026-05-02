"""Unit tests for the tag-affinity ordering algorithm."""

from __future__ import annotations

import random

from chatgpt_library_archiver.affinity import compute_affinity_indices
from chatgpt_library_archiver.metadata import GalleryItem


def _item(id_: str, tags: list[str], created_at: float = 0.0) -> GalleryItem:
    return GalleryItem(id=id_, filename=f"{id_}.png", tags=tags, created_at=created_at)


def test_empty_input_no_error() -> None:
    compute_affinity_indices([])  # must not raise


def test_no_tags_yields_none() -> None:
    items = [_item("a", []), _item("b", [])]
    compute_affinity_indices(items)
    assert all(item.affinity_index is None for item in items)


def test_single_tagged_item_gets_zero() -> None:
    items = [_item("a", ["x"])]
    compute_affinity_indices(items)
    assert items[0].affinity_index == 0


def test_overlapping_tag_clusters_are_adjacent() -> None:
    # Three tag clusters: {x,y}, {p,q}, {m,n}
    items = [
        _item("c1", ["x", "y"]),
        _item("p1", ["p", "q"]),
        _item("c2", ["x", "y", "z"]),
        _item("p2", ["p", "q", "r"]),
        _item("m1", ["m", "n"]),
        _item("c3", ["x", "y"]),
    ]
    compute_affinity_indices(items)
    by_id = {item.id: item.affinity_index for item in items}
    # Each cluster's three (or two) members should occupy contiguous indices.
    cluster_x = sorted(by_id[i] for i in ("c1", "c2", "c3"))
    cluster_p = sorted(by_id[i] for i in ("p1", "p2"))
    assert cluster_x == [cluster_x[0], cluster_x[0] + 1, cluster_x[0] + 2]
    assert cluster_p == [cluster_p[0], cluster_p[0] + 1]


def test_items_with_no_tags_get_none_alongside_tagged() -> None:
    items = [
        _item("a", ["x", "y"]),
        _item("b", []),
        _item("c", ["x"]),
    ]
    compute_affinity_indices(items)
    by_id = {item.id: item.affinity_index for item in items}
    assert by_id["b"] is None
    assert by_id["a"] is not None
    assert by_id["c"] is not None
    assert {by_id["a"], by_id["c"]} == {0, 1}


def test_deterministic_under_input_shuffle() -> None:
    base = [
        _item("a", ["x", "y"], created_at=1.0),
        _item("b", ["y", "z"], created_at=2.0),
        _item("c", ["x", "z"], created_at=3.0),
        _item("d", ["q"], created_at=4.0),
        _item("e", ["q", "x"], created_at=5.0),
    ]

    def run(seed: int) -> dict[str, int | None]:
        rnd = random.Random(seed)  # noqa: S311 -- deterministic test shuffle, not crypto
        copy = [
            GalleryItem(
                id=i.id,
                filename=i.filename,
                tags=list(i.tags),
                created_at=i.created_at,
            )
            for i in base
        ]
        rnd.shuffle(copy)
        compute_affinity_indices(copy)
        return {item.id: item.affinity_index for item in copy}

    first = run(1)
    for seed in range(2, 8):
        assert run(seed) == first


def test_all_disjoint_tags_still_assigns_contiguous_indices() -> None:
    items = [_item(f"i{n}", [f"t{n}"]) for n in range(5)]
    compute_affinity_indices(items)
    indices = sorted(item.affinity_index for item in items)
    assert indices == [0, 1, 2, 3, 4]
