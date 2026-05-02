"""Tests for the ``gallery <verb>`` subcommand surface and the
``management`` module helpers."""

from __future__ import annotations

import csv
import importlib
import io
import json
import sys
from pathlib import Path

import pytest

from chatgpt_library_archiver import management
from chatgpt_library_archiver.metadata import (
    GalleryItem,
    load_gallery_items,
    save_gallery_items,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(
    *,
    id: str,
    filename: str,
    tags: list[str] | None = None,
    title: str = "",
    prompt: str | None = None,
    created_at: float | None = None,
    extra: dict[str, object] | None = None,
    thumbnails: dict[str, str] | None = None,
    checksum: str | None = None,
) -> GalleryItem:
    return GalleryItem(
        id=id,
        filename=filename,
        title=title,
        prompt=prompt,
        tags=list(tags or []),
        created_at=created_at,
        thumbnails=dict(thumbnails or {}),
        extra=dict(extra or {}),
        checksum=checksum,
    )


@pytest.fixture
def populated_gallery(gallery_dir: Path) -> Path:
    """Gallery dir with three items, image files, and one thumbnail tier."""

    items = [
        _make_item(
            id="a",
            filename="a.png",
            title="Alpha",
            prompt="sunset over hills",
            tags=["sunset", "landscape"],
            created_at=1000.0,
            extra={"model": "dall-e-3"},
            thumbnails={
                "small": "thumbs/small/a.png",
                "medium": "thumbs/medium/a.png",
                "large": "thumbs/large/a.png",
            },
            checksum="aaa111",
        ),
        _make_item(
            id="b",
            filename="b.png",
            title="Beta",
            prompt="city at night",
            tags=["city", "landscape"],
            created_at=2000.0,
            extra={"model": "gpt-image-1"},
            checksum="bbb222",
        ),
        _make_item(
            id="c",
            filename="c.png",
            title="Gamma",
            tags=[],
            created_at=3000.0,
            checksum="aaa111",  # duplicate checksum with item a
        ),
    ]
    save_gallery_items(gallery_dir, items)
    for item in items:
        (gallery_dir / "images" / item.filename).write_bytes(b"\x89PNG\r\n\x1a\n")
    for size in ("small", "medium", "large"):
        (gallery_dir / "thumbs" / size / "a.png").write_bytes(b"thumb")
    return gallery_dir


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_query_filters_by_tag(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    results = management.query_items(items, management.QueryFilters(tags=["landscape"]))
    assert sorted(it.id for it in results) == ["a", "b"]


def test_query_filters_by_excluded_tag(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    results = management.query_items(
        items, management.QueryFilters(excluded_tags=["sunset"])
    )
    assert sorted(it.id for it in results) == ["b", "c"]


def test_query_filters_by_extra(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    results = management.query_items(
        items,
        management.QueryFilters(extra=[("model", "dall-e-3")]),
    )
    assert [it.id for it in results] == ["a"]


def test_query_filters_by_title_and_prompt(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    title_results = management.query_items(
        items, management.QueryFilters(title_contains="alp")
    )
    assert [it.id for it in title_results] == ["a"]
    prompt_results = management.query_items(
        items, management.QueryFilters(prompt_contains="city")
    )
    assert [it.id for it in prompt_results] == ["b"]


def test_query_filters_by_created_range_and_thumbnail(
    populated_gallery: Path,
) -> None:
    items = load_gallery_items(populated_gallery)
    results = management.query_items(
        items,
        management.QueryFilters(
            created_after=1500.0,
            created_before=2500.0,
            has_thumbnail=False,
        ),
    )
    assert [it.id for it in results] == ["b"]


def test_query_limit_caps_results(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    results = management.query_items(items, management.QueryFilters(limit=2))
    assert len(results) == 2


def test_format_query_json_roundtrips(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    payload = json.loads(management.format_query_json(items))
    assert {row["id"] for row in payload} == {"a", "b", "c"}


def test_format_export_csv_includes_columns(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    text = management.format_export_csv(items)
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert rows[0][:3] == ["id", "filename", "title"]
    assert {row[0] for row in rows[1:]} == {"a", "b", "c"}


def test_add_tags_normalizes_and_dedupes() -> None:
    item = _make_item(id="x", filename="x.png", tags=["sunset"])
    added = management.add_tags(item, ["Sunset", "Beach!"])
    assert added == 1
    assert item.tags == ["sunset", "beach"]


def test_remove_tags_drops_matching() -> None:
    item = _make_item(id="x", filename="x.png", tags=["sunset", "beach"])
    removed = management.remove_tags(item, ["Sunset"])
    assert removed == 1
    assert item.tags == ["beach"]


def test_set_field_and_unset_field() -> None:
    item = _make_item(id="x", filename="x.png", title="old", tags=["t"])
    management.set_field(item, "title", "new")
    assert item.title == "new"
    management.set_field(item, "created_at", "1700000000")
    assert item.created_at == 1700000000.0
    management.unset_field(item, "title")
    assert item.title == ""
    management.unset_field(item, "tags")
    assert item.tags == []


def test_unset_field_removes_extra_key() -> None:
    item = _make_item(id="x", filename="x.png", extra={"model": "dall-e-3"})
    management.unset_field(item, "model")
    assert "model" not in item.extra


def test_unset_field_unknown_raises() -> None:
    item = _make_item(id="x", filename="x.png")
    with pytest.raises(KeyError):
        management.unset_field(item, "bogus")


def test_remove_items_deletes_files(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    survivors, reports = management.remove_items(
        list(items), ["a"], gallery_root=populated_gallery
    )
    assert [it.id for it in survivors] == ["b", "c"]
    assert reports[0].image_removed is True
    assert reports[0].thumbnails_removed == 3
    assert not (populated_gallery / "images" / "a.png").exists()
    for size in ("small", "medium", "large"):
        assert not (populated_gallery / "thumbs" / size / "a.png").exists()


def test_remove_items_tolerates_missing_image(populated_gallery: Path) -> None:
    (populated_gallery / "images" / "a.png").unlink()
    items = load_gallery_items(populated_gallery)
    survivors, reports = management.remove_items(
        list(items), ["a"], gallery_root=populated_gallery
    )
    assert reports[0].image_removed is False
    assert "a" not in {it.id for it in survivors}


def test_rename_item_moves_image_and_thumbnails(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "a")
    report = management.rename_item(item, "alpha.png", gallery_root=populated_gallery)
    assert item.filename == "alpha.png"
    assert (populated_gallery / "images" / "alpha.png").exists()
    for size in ("small", "medium", "large"):
        assert (populated_gallery / "thumbs" / size / "alpha.png").exists()
        assert not (populated_gallery / "thumbs" / size / "a.png").exists()
    assert all(rel.endswith("alpha.png") for rel in item.thumbnails.values())
    assert len(report.renamed_paths) == 4


def test_rename_item_rolls_back_on_collision(populated_gallery: Path) -> None:
    # Pre-create a colliding small thumbnail for the target name so the
    # validator (run before any rename) raises.
    (populated_gallery / "thumbs" / "small" / "alpha.png").write_bytes(b"x")
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "a")
    with pytest.raises(FileExistsError):
        management.rename_item(item, "alpha.png", gallery_root=populated_gallery)
    # Original files are untouched.
    assert (populated_gallery / "images" / "a.png").exists()
    for size in ("small", "medium", "large"):
        assert (populated_gallery / "thumbs" / size / "a.png").exists()
    assert item.filename == "a.png"


def test_rename_item_rolls_back_when_thumbnail_rename_fails(
    populated_gallery: Path, monkeypatch
) -> None:
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "a")
    real_rename = Path.rename
    calls = {"count": 0}

    def flaky(self: Path, target):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        if calls["count"] == 3:
            raise OSError("simulated failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    with pytest.raises(OSError):
        management.rename_item(item, "alpha.png", gallery_root=populated_gallery)

    assert (populated_gallery / "images" / "a.png").exists()
    assert not (populated_gallery / "images" / "alpha.png").exists()
    assert item.filename == "a.png"


def test_rename_rejects_path_traversal(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "a")
    with pytest.raises(ValueError):
        management.rename_item(item, "../escape.png", gallery_root=populated_gallery)


def test_compute_stats(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    stats = management.compute_stats(items, gallery_root=populated_gallery)
    assert stats.total_items == 3
    assert stats.tagged_items == 2
    assert stats.untagged_items == 1
    assert dict(stats.top_tags)["landscape"] == 2
    assert stats.total_image_bytes > 0


def test_find_duplicates(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    groups = management.find_duplicates(items)
    assert any(g.kind == "checksum" and g.key == "aaa111" for g in groups)


def test_verify_items_reports_missing(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    (populated_gallery / "images" / "b.png").unlink()
    reports = management.verify_items(items, gallery_root=populated_gallery)
    assert any(r.item_id == "b" and not r.image_present for r in reports)


def test_prune_orphan_thumbnails(populated_gallery: Path) -> None:
    # Add an orphaned thumbnail.
    (populated_gallery / "thumbs" / "small" / "ghost.png").write_bytes(b"x")
    items = load_gallery_items(populated_gallery)
    removed = management.prune_orphan_thumbnails(items, gallery_root=populated_gallery)
    removed_names = {p.name for p in removed}
    assert "ghost.png" in removed_names
    assert "a.png" not in removed_names


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def _run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> list[str]:
    """Run the archiver CLI and return the captured printer output lines."""

    captured: list[str] = []
    monkeypatch.setattr(sys, "argv", ["chatgpt_library_archiver", *argv])
    cli = importlib.import_module("chatgpt_library_archiver.__main__")
    cli.main(printer=lambda line: captured.append(str(line)))
    return captured


def test_gallery_bare_aliases_build(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    monkeypatch.chdir(populated_gallery.parent)
    out = _run_cli(monkeypatch, "gallery", "--gallery", str(populated_gallery))
    assert (populated_gallery / "index.html").exists()
    assert any("Generated gallery" in line for line in out)


def test_gallery_query_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--tag",
        "landscape",
        "--format",
        "json",
    )
    payload = json.loads(out[0])
    assert sorted(row["id"] for row in payload) == ["a", "b"]


def test_gallery_query_extra_filter(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--extra",
        "model=gpt-image-1",
        "--format",
        "json",
    )
    payload = json.loads(out[0])
    assert [row["id"] for row in payload] == ["b"]


def test_gallery_show_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "show",
        "a",
        "--gallery",
        str(populated_gallery),
        "--json",
    )
    payload = json.loads(out[0])
    assert payload["id"] == "a"


def test_gallery_tag_and_untag_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    _run_cli(
        monkeypatch,
        "gallery",
        "tag",
        "c",
        "--gallery",
        str(populated_gallery),
        "Sunny",
        "Coast",
    )
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "c")
    assert item.tags == ["sunny", "coast"]

    _run_cli(
        monkeypatch,
        "gallery",
        "untag",
        "c",
        "--gallery",
        str(populated_gallery),
        "sunny",
    )
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "c")
    assert item.tags == ["coast"]


def test_gallery_set_and_unset_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    _run_cli(
        monkeypatch,
        "gallery",
        "set",
        "a",
        "--gallery",
        str(populated_gallery),
        "--title",
        "Renamed Alpha",
    )
    items = load_gallery_items(populated_gallery)
    assert next(it for it in items if it.id == "a").title == "Renamed Alpha"

    _run_cli(
        monkeypatch,
        "gallery",
        "unset",
        "a",
        "prompt",
        "--gallery",
        str(populated_gallery),
    )
    items = load_gallery_items(populated_gallery)
    assert next(it for it in items if it.id == "a").prompt is None


def test_gallery_rm_requires_yes(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    monkeypatch.delenv("ARCHIVER_ASSUME_YES", raising=False)
    out = _run_cli(
        monkeypatch,
        "gallery",
        "rm",
        "a",
        "--gallery",
        str(populated_gallery),
    )
    assert any("Refusing to delete" in line for line in out)
    assert (populated_gallery / "images" / "a.png").exists()


def test_gallery_rm_with_yes_flag(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    _run_cli(
        monkeypatch,
        "gallery",
        "rm",
        "a",
        "--yes",
        "--gallery",
        str(populated_gallery),
    )
    items = load_gallery_items(populated_gallery)
    assert "a" not in {it.id for it in items}
    assert not (populated_gallery / "images" / "a.png").exists()


def test_gallery_mv_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    _run_cli(
        monkeypatch,
        "gallery",
        "mv",
        "a",
        "alpha.png",
        "--gallery",
        str(populated_gallery),
    )
    items = load_gallery_items(populated_gallery)
    item = next(it for it in items if it.id == "a")
    assert item.filename == "alpha.png"
    assert (populated_gallery / "images" / "alpha.png").exists()


def test_gallery_stats_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "stats",
        "--gallery",
        str(populated_gallery),
    )
    joined = "\n".join(out)
    assert "total items:       3" in joined
    assert "landscape" in joined


def test_gallery_export_csv_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "export",
        "--gallery",
        str(populated_gallery),
        "--format",
        "csv",
    )
    reader = csv.reader(io.StringIO(out[0]))
    rows = list(reader)
    assert rows[0][0] == "id"
    assert {row[0] for row in rows[1:]} == {"a", "b", "c"}


def test_gallery_affinity_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    _run_cli(
        monkeypatch,
        "gallery",
        "affinity",
        "--gallery",
        str(populated_gallery),
    )
    items = load_gallery_items(populated_gallery)
    indices = {it.id: it.affinity_index for it in items}
    # Two tagged items should have indices, untagged item should be None.
    assert indices["a"] is not None
    assert indices["b"] is not None
    assert indices["c"] is None


def test_gallery_dedupe_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "dedupe",
        "--gallery",
        str(populated_gallery),
    )
    assert any("aaa111" in line for line in out)


def test_gallery_verify_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    (populated_gallery / "images" / "b.png").unlink()
    out = _run_cli(
        monkeypatch,
        "gallery",
        "verify",
        "--gallery",
        str(populated_gallery),
    )
    assert any("b.png" in line for line in out)


def test_gallery_prune_thumbs_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    (populated_gallery / "thumbs" / "small" / "ghost.png").write_bytes(b"x")
    out = _run_cli(
        monkeypatch,
        "gallery",
        "prune-thumbs",
        "--gallery",
        str(populated_gallery),
    )
    assert any("ghost.png" in line for line in out)
    assert not (populated_gallery / "thumbs" / "small" / "ghost.png").exists()


# ---------------------------------------------------------------------------
# New query filter / sort / format coverage (M3)
# ---------------------------------------------------------------------------


def test_query_filters_by_has_tags_and_no_tags(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    has = management.query_items(items, management.QueryFilters(has_tags=True))
    assert sorted(it.id for it in has) == ["a", "b"]
    none = management.query_items(items, management.QueryFilters(has_tags=False))
    assert [it.id for it in none] == ["c"]


def test_query_filters_by_has_prompt_and_no_prompt(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    has = management.query_items(items, management.QueryFilters(has_prompt=True))
    assert sorted(it.id for it in has) == ["a", "b"]
    none = management.query_items(items, management.QueryFilters(has_prompt=False))
    assert [it.id for it in none] == ["c"]


def test_query_filters_by_conversation_id(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    items[0].conversation_id = "conv-xyz"
    save_gallery_items(populated_gallery, items)
    items = load_gallery_items(populated_gallery)
    results = management.query_items(
        items, management.QueryFilters(conversation_id="conv-xyz")
    )
    assert [it.id for it in results] == ["a"]


def test_query_filters_by_missing_file(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    (populated_gallery / "images" / "b.png").unlink()
    results = management.query_items(
        items,
        management.QueryFilters(missing_file=True, gallery_root=populated_gallery),
    )
    assert [it.id for it in results] == ["b"]


def test_query_sort_affinity_nulls_last(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    # Hand-set affinity_index so we don't depend on the recompute order.
    by_id = {it.id: it for it in items}
    by_id["a"].affinity_index = 5
    by_id["b"].affinity_index = 1
    by_id["c"].affinity_index = None
    sorted_items = management.query_items(
        items, management.QueryFilters(), sort="affinity"
    )
    assert [it.id for it in sorted_items] == ["b", "a", "c"]


def test_query_sort_title_reverse(populated_gallery: Path) -> None:
    items = load_gallery_items(populated_gallery)
    sorted_items = management.query_items(
        items, management.QueryFilters(), sort="title", reverse=True
    )
    assert [it.id for it in sorted_items] == ["c", "b", "a"]


def test_format_query_ids() -> None:
    items = [
        _make_item(id="x", filename="x.png"),
        _make_item(id="y", filename="y.png"),
    ]
    assert management.format_query_ids(items) == "x\ny"


def test_gallery_query_format_ids_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--no-tags",
        "--format",
        "ids",
    )
    assert out[0] == "c"


def test_gallery_query_sort_affinity_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    # Build the gallery once so affinity_index is populated, then query
    # with --sort=affinity.
    _run_cli(
        monkeypatch,
        "gallery",
        "affinity",
        "--gallery",
        str(populated_gallery),
    )
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--sort",
        "affinity",
        "--format",
        "ids",
    )
    # All three items appear; the untagged "c" sorts last (nulls last).
    ids = out[0].splitlines()
    assert set(ids) == {"a", "b", "c"}
    assert ids[-1] == "c"


def test_gallery_query_since_alias_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--since",
        "2500",
        "--format",
        "ids",
    )
    assert out[0] == "c"


def test_gallery_query_until_alias_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--until",
        "1500",
        "--format",
        "ids",
    )
    assert out[0] == "a"


def test_gallery_query_missing_file_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    (populated_gallery / "images" / "b.png").unlink()
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--missing-file",
        "--format",
        "ids",
    )
    assert out[0] == "b"


def test_gallery_query_conversation_id_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    items = load_gallery_items(populated_gallery)
    items[0].conversation_id = "conv-1"
    save_gallery_items(populated_gallery, items)
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--conversation-id",
        "conv-1",
        "--format",
        "ids",
    )
    assert out[0] == "a"


def test_gallery_query_has_prompt_cli(
    monkeypatch: pytest.MonkeyPatch, populated_gallery: Path
) -> None:
    out = _run_cli(
        monkeypatch,
        "gallery",
        "query",
        "--gallery",
        str(populated_gallery),
        "--no-prompt",
        "--format",
        "ids",
    )
    assert out[0] == "c"
