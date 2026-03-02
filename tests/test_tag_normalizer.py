"""Tests for tag normalization and consolidation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from chatgpt_library_archiver import tagger
from chatgpt_library_archiver.metadata import GalleryItem, load_gallery_items
from chatgpt_library_archiver.tag_normalizer import (
    TagGroup,
    apply_consolidation,
    consolidate_tags,
    find_similar_groups,
    normalize_all_tags,
)
from chatgpt_library_archiver.tagger import normalize_tag

# ---------------------------------------------------------------------------
# normalize_tag unit tests
# ---------------------------------------------------------------------------


class TestNormalizeTag:
    def test_strips_html(self):
        assert normalize_tag("<b>dog</b>") == "dog"

    def test_replaces_underscores_with_spaces(self):
        assert normalize_tag("black_fur") == "black fur"

    def test_collapses_whitespace(self):
        assert normalize_tag("  multiple   spaces  ") == "multiple spaces"

    def test_lowercases(self):
        assert normalize_tag("Fantasy Creature") == "fantasy creature"

    def test_strips_trailing_punctuation(self):
        assert normalize_tag("animal character.") == "animal character"
        assert normalize_tag("wow!") == "wow"
        assert normalize_tag("huh?") == "huh"
        assert normalize_tag("list,") == "list"
        assert normalize_tag("pause;") == "pause"
        assert normalize_tag("colon:") == "colon"

    def test_combined_normalization(self):
        assert normalize_tag("  Black_Fur.  ") == "black fur"

    def test_empty_after_normalization(self):
        assert normalize_tag("<b></b>") == ""

    def test_only_punctuation(self):
        assert normalize_tag("...") == ""

    def test_multiple_trailing_punctuation(self):
        assert normalize_tag("hello...") == "hello"


# ---------------------------------------------------------------------------
# generate_tags integration with normalize_tag
# ---------------------------------------------------------------------------


class _FakeTelemetry:
    total_tokens = 10
    latency_s = 0.1
    retries = 0


def _parse_via_generate_tags(monkeypatch, raw_text: str) -> list[str]:
    monkeypatch.setattr(
        tagger,
        "call_image_endpoint",
        lambda **kw: (raw_text, _FakeTelemetry(), None),
    )
    from unittest.mock import MagicMock

    tags, _ = tagger.generate_tags(
        image_path="dummy.jpg",
        client=MagicMock(),
        model="m",
        prompt="p",
    )
    return tags


def test_generate_tags_strips_trailing_punctuation(monkeypatch):
    tags = _parse_via_generate_tags(monkeypatch, "animal character., sunset!")
    assert "animal character" in tags
    assert "sunset" in tags


def test_generate_tags_replaces_underscores(monkeypatch):
    tags = _parse_via_generate_tags(monkeypatch, "black_fur, red_eyes")
    assert "black fur" in tags
    assert "red eyes" in tags


def test_generate_tags_deduplicates_after_normalization(monkeypatch):
    # "Black_fur" and "black fur" should collapse to one entry
    tags = _parse_via_generate_tags(monkeypatch, "Black_fur, black fur")
    assert tags == ["black fur"]


# ---------------------------------------------------------------------------
# normalize_all_tags tests
# ---------------------------------------------------------------------------


def test_normalize_all_tags_fixes_underscores(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["black_fur", "Red_Eyes"]},
            {"id": "2", "filename": "b.jpg", "tags": ["clean"]},
        ],
    )
    count = normalize_all_tags(str(gallery))
    assert count == 1  # only item 1 changed

    items = load_gallery_items(str(gallery))
    assert items[0].tags == ["black fur", "red eyes"]
    assert items[1].tags == ["clean"]


def test_normalize_all_tags_dry_run(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [{"id": "1", "filename": "a.jpg", "tags": ["Black_Fur."]}],
    )
    count = normalize_all_tags(str(gallery), dry_run=True)
    assert count == 1

    # Metadata should NOT have been modified.
    items = load_gallery_items(str(gallery))
    assert items[0].tags == ["Black_Fur."]


def test_normalize_all_tags_removes_dups(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [{"id": "1", "filename": "a.jpg", "tags": ["Cat", "cat"]}],
    )
    count = normalize_all_tags(str(gallery))
    assert count == 1
    items = load_gallery_items(str(gallery))
    assert items[0].tags == ["cat"]


# ---------------------------------------------------------------------------
# find_similar_groups tests
# ---------------------------------------------------------------------------


def _make_items(tag_counts: dict[str, int]) -> list[GalleryItem]:
    """Create GalleryItem list where each tag appears *count* times."""
    items: list[GalleryItem] = []
    idx = 0
    for tag, count in tag_counts.items():
        for _ in range(count):
            idx += 1
            items.append(
                GalleryItem(
                    id=str(idx),
                    filename=f"{idx}.jpg",
                    tags=[tag],
                )
            )
    return items


def test_find_singular_plural(tmp_path, write_metadata):
    items = _make_items({"fantasy creature": 100, "fantasy creatures": 3})
    gallery = write_metadata(
        tmp_path / "gallery",
        [it.to_dict() for it in items],
    )
    groups = find_similar_groups(str(gallery))
    assert len(groups) >= 1
    group = groups[0]
    assert group.canonical == "fantasy creature"
    assert "fantasy creatures" in group.variants
    assert group.confidence == "high"


def test_find_similar_groups_sorted_by_count(tmp_path, write_metadata):
    items = _make_items(
        {
            "cat": 50,
            "cats": 5,
            "dog": 200,
            "dogs": 10,
        }
    )
    gallery = write_metadata(
        tmp_path / "gallery",
        [it.to_dict() for it in items],
    )
    groups = find_similar_groups(str(gallery))
    assert len(groups) >= 2
    # "dog/dogs" (total 210) should come before "cat/cats" (total 55)
    assert groups[0].canonical == "dog"
    assert groups[1].canonical == "cat"


def test_find_similar_groups_canonical_is_most_frequent(tmp_path, write_metadata):
    # Plural form is more common → it becomes canonical.
    items = _make_items({"apples": 80, "apple": 2})
    gallery = write_metadata(
        tmp_path / "gallery",
        [it.to_dict() for it in items],
    )
    groups = find_similar_groups(str(gallery))
    assert len(groups) == 1
    assert groups[0].canonical == "apples"


def test_find_similar_groups_fuzzy(tmp_path, write_metadata):
    items = _make_items({"3d render": 50, "3d rendering": 10})
    gallery = write_metadata(
        tmp_path / "gallery",
        [it.to_dict() for it in items],
    )
    groups = find_similar_groups(str(gallery))
    # Should find a fuzzy match
    assert len(groups) >= 1
    all_tags = set()
    for g in groups:
        all_tags.add(g.canonical)
        all_tags.update(g.variants)
    assert "3d render" in all_tags
    assert "3d rendering" in all_tags


def test_find_similar_groups_empty_gallery(tmp_path, write_metadata):
    gallery = write_metadata(tmp_path / "gallery", [])
    groups = find_similar_groups(str(gallery))
    assert groups == []


# ---------------------------------------------------------------------------
# apply_consolidation tests
# ---------------------------------------------------------------------------


def test_apply_consolidation_merges_tags():
    items = [
        GalleryItem(id="1", filename="a.jpg", tags=["fantasy creatures", "sunset"]),
        GalleryItem(id="2", filename="b.jpg", tags=["fantasy creature"]),
        GalleryItem(id="3", filename="c.jpg", tags=["sunset"]),
    ]
    merges = [("fantasy creature", ["fantasy creatures"])]
    count = apply_consolidation(items, merges)
    assert count == 1  # only item 1 changed
    assert items[0].tags == ["fantasy creature", "sunset"]
    assert items[1].tags == ["fantasy creature"]  # unchanged
    assert items[2].tags == ["sunset"]  # unchanged


def test_apply_consolidation_deduplicates():
    items = [
        GalleryItem(
            id="1",
            filename="a.jpg",
            tags=["fantasy creature", "fantasy creatures"],
        ),
    ]
    merges = [("fantasy creature", ["fantasy creatures"])]
    count = apply_consolidation(items, merges)
    assert count == 1
    assert items[0].tags == ["fantasy creature"]


def test_apply_consolidation_empty_merges():
    items = [GalleryItem(id="1", filename="a.jpg", tags=["cat"])]
    count = apply_consolidation(items, [])
    assert count == 0


# ---------------------------------------------------------------------------
# consolidate_tags orchestrator tests
# ---------------------------------------------------------------------------


def test_consolidate_tags_dry_run(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["cat", "cats"]},
            {"id": "2", "filename": "b.jpg", "tags": ["cat"]},
            {"id": "3", "filename": "c.jpg", "tags": ["cats"]},
        ],
    )
    output: list[str] = []
    consolidate_tags(
        str(gallery),
        auto_apply=True,
        dry_run=True,
        printer=output.append,
    )
    # dry_run still returns the count of items that *would* change
    # (normalization count, since merges aren't applied in dry run)
    raw = json.loads((gallery / "metadata.json").read_text())
    # Metadata not modified
    assert raw[0]["tags"] == ["cat", "cats"]

    # Output should mention dry run
    full = "\n".join(output)
    assert "Dry run" in full


def test_consolidate_tags_auto_apply(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["cat"]},
            {"id": "2", "filename": "b.jpg", "tags": ["cats"]},
        ],
    )
    output: list[str] = []
    count = consolidate_tags(
        str(gallery),
        auto_apply=True,
        interactive=False,
        printer=output.append,
    )
    assert count >= 1

    items = load_gallery_items(str(gallery))
    # Both items should now have the canonical form
    all_tags = {tag for item in items for tag in item.tags}
    # Should have merged to one form
    assert len(all_tags) == 1


def test_consolidate_tags_interactive_accept(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["cat"]},
            {"id": "2", "filename": "b.jpg", "tags": ["cats"]},
        ],
    )
    output: list[str] = []
    count = consolidate_tags(
        str(gallery),
        auto_apply=False,
        interactive=True,
        printer=output.append,
        prompter=lambda _prompt: "y",
    )
    assert count >= 1


def test_consolidate_tags_interactive_reject(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["cat"]},
            {"id": "2", "filename": "b.jpg", "tags": ["cats"]},
        ],
    )
    output: list[str] = []
    consolidate_tags(
        str(gallery),
        auto_apply=False,
        interactive=True,
        printer=output.append,
        prompter=lambda _prompt: "n",
    )
    # No merges applied, but normalization may have run
    items = load_gallery_items(str(gallery))
    all_tags = {tag for item in items for tag in item.tags}
    assert "cat" in all_tags
    assert "cats" in all_tags


def test_consolidate_tags_no_groups(tmp_path, write_metadata):
    gallery = write_metadata(
        tmp_path / "gallery",
        [
            {"id": "1", "filename": "a.jpg", "tags": ["cat"]},
            {"id": "2", "filename": "b.jpg", "tags": ["dog"]},
        ],
    )
    output: list[str] = []
    count = consolidate_tags(
        str(gallery),
        auto_apply=True,
        printer=output.append,
    )
    assert count == 0
    full = "\n".join(output)
    assert "No near-duplicate" in full


# ---------------------------------------------------------------------------
# TagGroup dataclass tests
# ---------------------------------------------------------------------------


def test_tag_group_total_count():
    g = TagGroup(
        canonical="cat",
        variants=["cats"],
        count_by_tag={"cat": 50, "cats": 5},
        confidence="high",
    )
    assert g.total_count == 55


# ---------------------------------------------------------------------------
# normalize_tag — additional edge cases
# ---------------------------------------------------------------------------


class TestNormalizeTagEdgeCases:
    def test_mixed_underscores_and_spaces(self):
        assert normalize_tag("black_and white_cat") == "black and white cat"

    def test_html_entities_not_stripped(self):
        # HTML entities are plain text after tag stripping — they survive.
        assert normalize_tag("&amp; hello") == "&amp; hello"

    def test_nested_html_tags(self):
        assert normalize_tag("<b><i>bold italic</i></b>") == "bold italic"

    def test_self_closing_html(self):
        assert normalize_tag("before<br/>after") == "beforeafter"

    def test_idempotency(self):
        """Already-normalized tags should survive a second pass unchanged."""
        for tag in ("black fur", "fantasy creature", "3d render", "sunset"):
            assert normalize_tag(normalize_tag(tag)) == normalize_tag(tag)

    def test_very_long_tag(self):
        long_tag = "a" * 500
        assert normalize_tag(long_tag) == long_tag

    def test_leading_punctuation_preserved(self):
        """Leading punctuation should NOT be stripped — only trailing."""
        assert normalize_tag("...hello") == "...hello"
        assert normalize_tag("!important") == "!important"
        assert normalize_tag(".hidden") == ".hidden"

    def test_only_whitespace(self):
        assert normalize_tag("   ") == ""

    def test_unicode_preserved(self):
        assert normalize_tag("café_latte") == "café latte"

    def test_numeric_tag(self):
        assert normalize_tag("42") == "42"

    def test_tag_with_internal_punctuation(self):
        """Internal punctuation (hyphens, apostrophes) should be preserved."""
        assert normalize_tag("sci-fi") == "sci-fi"
        assert normalize_tag("it's") == "it's"

    def test_multiple_html_interleaved_with_text(self):
        assert normalize_tag("<b>hello</b> <i>world</i>") == "hello world"


# ---------------------------------------------------------------------------
# find_similar_groups — additional edge cases
# ---------------------------------------------------------------------------


class TestFindSimilarGroupsEdgeCases:
    def test_y_to_ies_plural(self, tmp_path, write_metadata):
        """'puppy' and 'puppies' should be grouped together."""
        items = _make_items({"puppy": 50, "puppies": 10})
        gallery = write_metadata(
            tmp_path / "gallery",
            [it.to_dict() for it in items],
        )
        groups = find_similar_groups(str(gallery))
        assert len(groups) >= 1
        all_tags = set()
        for g in groups:
            all_tags.add(g.canonical)
            all_tags.update(g.variants)
        assert "puppy" in all_tags
        assert "puppies" in all_tags

    def test_y_to_ies_plural_canonical_is_most_common(self, tmp_path, write_metadata):
        """When the -ies form is more common, it should be canonical."""
        items = _make_items({"puppy": 2, "puppies": 80})
        gallery = write_metadata(
            tmp_path / "gallery",
            [it.to_dict() for it in items],
        )
        groups = find_similar_groups(str(gallery))
        assert len(groups) == 1
        assert groups[0].canonical == "puppies"

    def test_tag_assigned_to_only_one_group(self, tmp_path, write_metadata):
        """A tag that could match multiple groups should only appear in one."""
        items = _make_items({"cat": 50, "cats": 5, "dog": 40, "dogs": 3})
        gallery = write_metadata(
            tmp_path / "gallery",
            [it.to_dict() for it in items],
        )
        groups = find_similar_groups(str(gallery))
        # Each variant/canonical appears in exactly one group
        seen: set[str] = set()
        for g in groups:
            members = {g.canonical} | set(g.variants)
            assert not members & seen, f"Tags {members & seen} in multiple groups"
            seen.update(members)

    def test_tags_below_fuzzy_threshold_not_grouped(self, tmp_path, write_metadata):
        """Very different tags should not be grouped, even if both exist."""
        items = _make_items({"cat": 50, "waterfall": 50})
        gallery = write_metadata(
            tmp_path / "gallery",
            [it.to_dict() for it in items],
        )
        groups = find_similar_groups(str(gallery))
        assert groups == []

    def test_single_tag_no_groups(self, tmp_path, write_metadata):
        items = _make_items({"landscape": 30})
        gallery = write_metadata(
            tmp_path / "gallery",
            [it.to_dict() for it in items],
        )
        groups = find_similar_groups(str(gallery))
        assert groups == []

    def test_es_plural(self, tmp_path, write_metadata):
        """Tags ending in -es (e.g. 'box' / 'boxes') should be grouped."""
        items = _make_items({"box": 40, "boxes": 5})
        gallery = write_metadata(
            tmp_path / "gallery",
            [it.to_dict() for it in items],
        )
        groups = find_similar_groups(str(gallery))
        assert len(groups) >= 1
        all_tags = set()
        for g in groups:
            all_tags.add(g.canonical)
            all_tags.update(g.variants)
        assert "box" in all_tags
        assert "boxes" in all_tags


# ---------------------------------------------------------------------------
# apply_consolidation — additional edge cases
# ---------------------------------------------------------------------------


class TestApplyConsolidationEdgeCases:
    def test_merge_not_matching_any_tags(self):
        """Merges for tags that don't exist in any item should be a no-op."""
        items = [GalleryItem(id="1", filename="a.jpg", tags=["sunset"])]
        merges = [("ocean", ["oceans"])]
        count = apply_consolidation(items, merges)
        assert count == 0
        assert items[0].tags == ["sunset"]

    def test_item_has_both_canonical_and_variant(self):
        """Item with both 'cat' and 'cats' should deduplicate to just 'cat'."""
        items = [
            GalleryItem(id="1", filename="a.jpg", tags=["cat", "cats"]),
        ]
        merges = [("cat", ["cats"])]
        count = apply_consolidation(items, merges)
        assert count == 1
        assert items[0].tags == ["cat"]

    def test_multiple_merges_applied(self):
        """Multiple merge rules applied in a single call."""
        items = [
            GalleryItem(
                id="1",
                filename="a.jpg",
                tags=["cats", "dogs", "sunset"],
            ),
        ]
        merges = [("cat", ["cats"]), ("dog", ["dogs"])]
        count = apply_consolidation(items, merges)
        assert count == 1
        assert items[0].tags == ["cat", "dog", "sunset"]

    def test_items_without_matching_tags_unchanged(self):
        items = [
            GalleryItem(id="1", filename="a.jpg", tags=["cat", "cats"]),
            GalleryItem(id="2", filename="b.jpg", tags=["sunset"]),
        ]
        merges = [("cat", ["cats"])]
        count = apply_consolidation(items, merges)
        assert count == 1  # only item 1
        assert items[1].tags == ["sunset"]


# ---------------------------------------------------------------------------
# consolidate_tags orchestrator — additional edge cases
# ---------------------------------------------------------------------------


class TestConsolidateTagsEdgeCases:
    def test_normalization_before_grouping(self, tmp_path, write_metadata):
        """Tags with underscores should be normalized before grouping runs."""
        gallery = write_metadata(
            tmp_path / "gallery",
            [
                {"id": "1", "filename": "a.jpg", "tags": ["black_fur"]},
                {"id": "2", "filename": "b.jpg", "tags": ["black fur"]},
            ],
        )
        output: list[str] = []
        count = consolidate_tags(
            str(gallery),
            auto_apply=True,
            printer=output.append,
        )
        # Both items should now read "black fur"; normalization collapses
        # "black_fur" → "black fur" so no grouping/merging is needed.
        items = load_gallery_items(str(gallery))
        assert all(item.tags == ["black fur"] for item in items)
        assert count >= 1  # at least item 1 was normalized

    def test_non_interactive_non_auto_skips_merges(self, tmp_path, write_metadata):
        """When interactive=False and auto_apply=False, merges are skipped."""
        gallery = write_metadata(
            tmp_path / "gallery",
            [{"id": str(i), "filename": f"{i}.jpg", "tags": ["cat"]} for i in range(50)]
            + [
                {"id": str(i), "filename": f"{i}.jpg", "tags": ["cats"]}
                for i in range(50, 55)
            ],
        )
        output: list[str] = []
        consolidate_tags(
            str(gallery),
            auto_apply=False,
            interactive=False,
            printer=output.append,
        )
        # Merges should be skipped, so "cats" still exists.
        items = load_gallery_items(str(gallery))
        all_tags = {tag for item in items for tag in item.tags}
        assert "cats" in all_tags
        # Output should mention "skipped"
        full = "\n".join(output)
        assert "skipped" in full.lower()

    def test_dry_run_does_not_save_merges(self, tmp_path, write_metadata):
        """Dry run should report groups but not persist any merge changes."""
        gallery = write_metadata(
            tmp_path / "gallery",
            [{"id": str(i), "filename": f"{i}.jpg", "tags": ["cat"]} for i in range(50)]
            + [
                {"id": str(i), "filename": f"{i}.jpg", "tags": ["cats"]}
                for i in range(50, 55)
            ],
        )
        output: list[str] = []
        consolidate_tags(
            str(gallery),
            auto_apply=True,
            dry_run=True,
            printer=output.append,
        )
        # File on disk should be unchanged.
        raw = json.loads((gallery / "metadata.json").read_text())
        all_raw_tags = {tag for item in raw for tag in item["tags"]}
        assert "cats" in all_raw_tags
        assert "cat" in all_raw_tags

    def test_empty_gallery(self, tmp_path, write_metadata):
        gallery = write_metadata(tmp_path / "gallery", [])
        output: list[str] = []
        count = consolidate_tags(
            str(gallery),
            auto_apply=True,
            printer=output.append,
        )
        assert count == 0

    def test_normalization_dedup_before_grouping(self, tmp_path, write_metadata):
        """Items with 'Cat' and 'cat' should be deduped during normalization
        so grouping doesn't see phantom duplicates."""
        gallery = write_metadata(
            tmp_path / "gallery",
            [
                {"id": "1", "filename": "a.jpg", "tags": ["Cat", "cat"]},
                {"id": "2", "filename": "b.jpg", "tags": ["dog"]},
            ],
        )
        output: list[str] = []
        count = consolidate_tags(
            str(gallery),
            auto_apply=True,
            printer=output.append,
        )
        items = load_gallery_items(str(gallery))
        assert items[0].tags == ["cat"]
        assert count >= 1


# ---------------------------------------------------------------------------
# generate_tags — additional integration edge cases
# ---------------------------------------------------------------------------


class _FakeTelemetryForEdge:
    total_tokens = 10
    latency_s = 0.1
    retries = 0


def _parse_tags(monkeypatch, raw_text: str) -> list[str]:
    """Helper: drive generate_tags with a fake call_image_endpoint."""
    monkeypatch.setattr(
        tagger,
        "call_image_endpoint",
        lambda **kw: (raw_text, _FakeTelemetryForEdge(), None),
    )
    tags, _ = tagger.generate_tags(
        image_path="dummy.jpg",
        client=MagicMock(),
        model="m",
        prompt="p",
    )
    return tags


def test_generate_tags_strips_html(monkeypatch):
    tags = _parse_tags(monkeypatch, "<b>nature</b>, <i>sunset</i>")
    assert "nature" in tags
    assert "sunset" in tags
    assert not any("<" in t for t in tags)


def test_generate_tags_filters_empty_tags(monkeypatch):
    """Blank entries from trailing commas or empty HTML should be dropped."""
    tags = _parse_tags(monkeypatch, "cat, , <b></b>, dog")
    assert tags == ["cat", "dog"]


def test_generate_tags_handles_newline_separated(monkeypatch):
    """Tags separated by newlines (common from LLMs) should be parsed."""
    tags = _parse_tags(monkeypatch, "nature\nsunset\nocean")
    assert tags == ["nature", "sunset", "ocean"]


def test_generate_tags_normalizes_and_deduplicates_complex(monkeypatch):
    """Complex normalization: underscore + case + trailing punct all at once."""
    tags = _parse_tags(monkeypatch, "Black_Fur., black fur, BLACK_FUR!")
    assert tags == ["black fur"]
