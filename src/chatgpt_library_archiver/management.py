"""Pure-Python helpers for the ``gallery`` management subcommands.

This module contains the query / mutate / inspection logic invoked by the
``gallery <verb>`` CLI surface.  Functions here operate on lists of
:class:`GalleryItem` and a gallery root :class:`~pathlib.Path` so they can be
unit tested without touching ``argparse``.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .metadata import GalleryItem, normalize_created_at
from .tagger import normalize_tag
from .thumbnails import THUMBNAIL_DIR_NAME, THUMBNAIL_SIZES

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def find_by_id(items: Sequence[GalleryItem], item_id: str) -> GalleryItem | None:
    """Return the first item matching ``item_id`` or ``None``."""

    for item in items:
        if item.id == item_id:
            return item
    return None


def partition_by_ids(
    items: Sequence[GalleryItem], ids: Iterable[str]
) -> tuple[list[GalleryItem], list[str]]:
    """Split ``items`` into (matched, missing-ids) for the given ``ids``."""

    id_set = list(ids)
    by_id = {item.id: item for item in items}
    matched: list[GalleryItem] = []
    missing: list[str] = []
    for ident in id_set:
        if ident in by_id:
            matched.append(by_id[ident])
        else:
            missing.append(ident)
    return matched, missing


# ---------------------------------------------------------------------------
# Query filters
# ---------------------------------------------------------------------------


@dataclass
class QueryFilters:
    """Optional predicates for :func:`query_items`."""

    ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)  # AND across required tags
    excluded_tags: list[str] = field(default_factory=list)
    title_contains: str | None = None
    prompt_contains: str | None = None
    filename_contains: str | None = None
    created_after: float | None = None
    created_before: float | None = None
    has_thumbnail: bool | None = None  # True/False/None (no filter)
    has_tags: bool | None = None  # True = at least one tag, False = no tags
    has_prompt: bool | None = None  # True = non-empty prompt, False = empty/None
    conversation_id: str | None = None
    missing_file: bool = False  # only items whose image file does not exist
    gallery_root: Path | None = None  # required when missing_file is True
    extra: list[tuple[str, str]] = field(default_factory=list)
    limit: int | None = None


def _matches(item: GalleryItem, filters: QueryFilters) -> bool:
    if filters.ids and item.id not in filters.ids:
        return False
    if filters.tags:
        item_tags = set(item.tags or [])
        if not all(t in item_tags for t in filters.tags):
            return False
    if filters.excluded_tags:
        item_tags = set(item.tags or [])
        if any(t in item_tags for t in filters.excluded_tags):
            return False
    if filters.title_contains is not None:
        needle = filters.title_contains.lower()
        if needle not in (item.title or "").lower():
            return False
    if filters.prompt_contains is not None:
        needle = filters.prompt_contains.lower()
        if needle not in (item.prompt or "").lower():
            return False
    if filters.filename_contains is not None:
        needle = filters.filename_contains.lower()
        if needle not in (item.filename or "").lower():
            return False
    if filters.created_after is not None and (
        item.created_at is None or item.created_at < filters.created_after
    ):
        return False
    if filters.created_before is not None and (
        item.created_at is None or item.created_at > filters.created_before
    ):
        return False
    if filters.has_thumbnail is True and not item.thumbnails:
        return False
    if filters.has_thumbnail is False and item.thumbnails:
        return False
    if filters.has_tags is True and not item.tags:
        return False
    if filters.has_tags is False and item.tags:
        return False
    if filters.has_prompt is True and not (item.prompt or "").strip():
        return False
    if filters.has_prompt is False and (item.prompt or "").strip():
        return False
    if filters.conversation_id is not None and item.conversation_id != (
        filters.conversation_id
    ):
        return False
    if filters.missing_file:
        if filters.gallery_root is None or not item.filename:
            return False
        if (filters.gallery_root / "images" / item.filename).exists():
            return False
    if filters.extra:
        for key, expected in filters.extra:
            actual = item.extra.get(key)
            if actual is None or str(actual) != expected:
                return False
    return True


def _sort_key(item: GalleryItem, mode: str) -> Any:
    """Return a sort key for ``item`` under ``mode``.

    ``affinity`` places items with no ``affinity_index`` last (nulls last)
    using ``(is_null, value)`` tuples.  ``created`` likewise treats missing
    timestamps as the latest possible value so they sort to the end.
    """

    if mode == "title":
        return ((item.title or "").lower(), item.id)
    if mode == "filename":
        return ((item.filename or "").lower(), item.id)
    if mode == "affinity":
        idx = item.affinity_index
        return (idx is None, idx if idx is not None else 0, item.id)
    # default: created_at ascending, nulls last
    ts = item.created_at
    return (ts is None, ts if ts is not None else 0.0, item.id)


_SORT_MODES = ("created", "title", "filename", "affinity")


def query_items(
    items: Sequence[GalleryItem],
    filters: QueryFilters,
    *,
    sort: str | None = None,
    reverse: bool = False,
) -> list[GalleryItem]:
    """Return items matching every supplied filter, capped by ``limit``.

    When ``sort`` is one of ``"created"``, ``"title"``, ``"filename"``, or
    ``"affinity"`` the matched list is reordered before truncation.  Nulls
    sort last for every mode; ``reverse`` flips the final ordering.
    """

    matched = [item for item in items if _matches(item, filters)]
    if sort is not None:
        if sort not in _SORT_MODES:
            raise ValueError(f"Unknown sort mode: {sort!r}")
        matched.sort(key=lambda it: _sort_key(it, sort), reverse=reverse)
    if filters.limit is not None and filters.limit >= 0:
        matched = matched[: filters.limit]
    return matched


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_query_plain(items: Sequence[GalleryItem]) -> str:
    """Render ``items`` as a fixed-width plain-text table."""

    if not items:
        return "(no matches)"

    headers = ("id", "filename", "title", "tags")
    rows: list[tuple[str, str, str, str]] = []
    for item in items:
        rows.append(
            (
                item.id,
                item.filename,
                (item.title or "").replace("\n", " "),
                ", ".join(item.tags or []),
            )
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def format_query_json(items: Sequence[GalleryItem]) -> str:
    """Render ``items`` as a JSON array."""

    return json.dumps([item.to_dict() for item in items], indent=2, default=str)


def format_query_ids(items: Sequence[GalleryItem]) -> str:
    """Render ``items`` as a newline-delimited list of ids.

    Suitable for piping into ``xargs gallery rm`` / ``gallery tag`` etc.
    """

    return "\n".join(item.id for item in items)


def format_show(item: GalleryItem, *, as_json: bool = False) -> str:
    """Render a single item as JSON or a human-readable block."""

    if as_json:
        return json.dumps(item.to_dict(), indent=2, default=str)
    payload = item.to_dict()
    lines: list[str] = []
    for key in (
        "id",
        "filename",
        "title",
        "prompt",
        "tags",
        "created_at",
        "width",
        "height",
        "url",
        "conversation_id",
        "message_id",
        "conversation_link",
        "thumbnail",
        "thumbnails",
        "checksum",
        "content_type",
        "affinity_index",
    ):
        value = payload.get(key)
        lines.append(f"{key}: {value!r}" if value is not None else f"{key}: -")
    if item.extra:
        lines.append("extra:")
        for k, v in item.extra.items():
            lines.append(f"  {k}: {v!r}")
    return "\n".join(lines)


def format_export_csv(items: Sequence[GalleryItem]) -> str:
    """Render ``items`` as CSV with a stable column order."""

    columns = [
        "id",
        "filename",
        "title",
        "prompt",
        "tags",
        "created_at",
        "width",
        "height",
        "url",
        "conversation_id",
        "message_id",
        "conversation_link",
        "checksum",
        "content_type",
        "affinity_index",
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for item in items:
        payload = item.to_dict()
        row: list[str] = []
        for col in columns:
            value = payload.get(col)
            if isinstance(value, list):
                row.append(",".join(str(v) for v in value))
            elif value is None:
                row.append("")
            else:
                row.append(str(value))
        writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def add_tags(item: GalleryItem, tags: Iterable[str]) -> int:
    """Add normalized ``tags`` to ``item``; return the count of new tags."""

    existing = list(item.tags or [])
    seen = set(existing)
    added = 0
    for raw in tags:
        tag = normalize_tag(raw)
        if not tag or tag in seen:
            continue
        existing.append(tag)
        seen.add(tag)
        added += 1
    item.tags = existing
    return added


def remove_tags(item: GalleryItem, tags: Iterable[str]) -> int:
    """Remove the normalized ``tags`` from ``item``; return removed count."""

    if not item.tags:
        return 0
    target = {normalize_tag(t) for t in tags if normalize_tag(t)}
    if not target:
        return 0
    new_tags = [t for t in item.tags if t not in target]
    removed = len(item.tags) - len(new_tags)
    item.tags = new_tags
    return removed


_SETTABLE_FIELDS: dict[str, Callable[[str], Any]] = {
    "title": str,
    "prompt": str,
    "url": str,
    "conversation_link": str,
    "conversation_id": str,
    "message_id": str,
    "checksum": str,
    "content_type": str,
    "created_at": normalize_created_at,
}


def settable_fields() -> tuple[str, ...]:
    """Return the names of fields supported by :func:`set_field`."""

    return tuple(_SETTABLE_FIELDS)


def set_field(item: GalleryItem, field_name: str, value: str) -> None:
    """Set a typed field on ``item``; raises ``KeyError`` for unknown fields."""

    if field_name not in _SETTABLE_FIELDS:
        raise KeyError(f"Unknown field: {field_name}")
    coerced = _SETTABLE_FIELDS[field_name](value)
    setattr(item, field_name, coerced)


_UNSETTABLE_FIELDS = {
    "title",
    "prompt",
    "url",
    "conversation_link",
    "conversation_id",
    "message_id",
    "checksum",
    "content_type",
    "created_at",
    "tags",
    "thumbnails",
    "thumbnail",
    "affinity_index",
}


def unset_field(item: GalleryItem, field_name: str) -> None:
    """Clear a field on ``item`` (or remove a key from ``item.extra``)."""

    if field_name in _UNSETTABLE_FIELDS:
        if field_name == "tags":
            item.tags = []
        elif field_name == "thumbnails":
            item.thumbnails = {}
        elif field_name == "title":
            item.title = ""
        else:
            setattr(item, field_name, None)
        return
    if field_name in item.extra:
        del item.extra[field_name]
        return
    raise KeyError(f"Unknown field: {field_name}")


# ---------------------------------------------------------------------------
# File-system helpers (rm / mv / verify / prune / dedupe)
# ---------------------------------------------------------------------------


def _safe_image_path(gallery_root: Path, filename: str) -> Path:
    """Resolve ``images/<filename>`` and refuse path traversal."""

    if not filename or "/" in filename or "\\" in filename:
        raise ValueError(f"Refusing unsafe image filename: {filename!r}")
    images_dir = (gallery_root / "images").resolve()
    candidate = (images_dir / filename).resolve()
    if not candidate.is_relative_to(images_dir):
        raise ValueError(f"Image filename escapes gallery: {filename!r}")
    return candidate


def _thumbnail_candidates(gallery_root: Path, filename: str) -> list[Path]:
    """Return on-disk thumbnail paths (both same-ext and .webp variants)."""

    thumbs_root = gallery_root / THUMBNAIL_DIR_NAME
    stem = Path(filename).stem
    paths: list[Path] = []
    for size in THUMBNAIL_SIZES:
        size_dir = thumbs_root / size
        same_ext = size_dir / filename
        webp_variant = size_dir / f"{stem}.webp"
        if same_ext.exists():
            paths.append(same_ext)
        if webp_variant.exists() and webp_variant != same_ext:
            paths.append(webp_variant)
    return paths


def delete_thumbnails(gallery_root: Path, filename: str) -> list[Path]:
    """Delete every on-disk thumbnail tied to ``filename``; return removed paths."""

    removed: list[Path] = []
    for path in _thumbnail_candidates(gallery_root, filename):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)
    return removed


@dataclass(slots=True)
class RemovalReport:
    """Summary of a single item's removal."""

    item_id: str
    metadata_removed: bool
    image_removed: bool
    thumbnails_removed: int
    error: str | None = None


def remove_items(
    items: list[GalleryItem],
    ids: Iterable[str],
    *,
    gallery_root: Path,
) -> tuple[list[GalleryItem], list[RemovalReport]]:
    """Remove items + on-disk image/thumbs for ``ids``.

    Returns the surviving items list and a per-id report.
    """

    id_set = set(ids)
    reports: list[RemovalReport] = []
    survivors: list[GalleryItem] = []

    for item in items:
        if item.id not in id_set:
            survivors.append(item)
            continue

        report = RemovalReport(
            item_id=item.id,
            metadata_removed=True,
            image_removed=False,
            thumbnails_removed=0,
        )
        try:
            image_path = _safe_image_path(gallery_root, item.filename)
        except ValueError as exc:
            report.error = str(exc)
            survivors.append(item)
            report.metadata_removed = False
            reports.append(report)
            continue

        try:
            if image_path.is_symlink():
                report.error = f"Refusing to delete symlinked image: {image_path}"
                survivors.append(item)
                report.metadata_removed = False
                reports.append(report)
                continue
            if image_path.exists():
                image_path.unlink()
                report.image_removed = True
        except OSError as exc:
            report.error = f"Failed to delete image: {exc}"

        removed_thumbs = delete_thumbnails(gallery_root, item.filename)
        report.thumbnails_removed = len(removed_thumbs)
        reports.append(report)

    return survivors, reports


@dataclass(slots=True)
class RenameReport:
    """Summary of ``mv`` operation."""

    item_id: str
    old_filename: str
    new_filename: str
    renamed_paths: list[tuple[Path, Path]]


def _check_rename_target(gallery_root: Path, new_filename: str) -> Path:
    """Validate ``new_filename`` and return the resolved target path."""

    if (
        not new_filename
        or "/" in new_filename
        or "\\" in new_filename
        or new_filename in {".", ".."}
    ):
        raise ValueError(f"Invalid target filename: {new_filename!r}")
    target = _safe_image_path(gallery_root, new_filename)
    if target.exists():
        raise FileExistsError(f"Target image already exists: {target}")
    stem = Path(new_filename).stem
    for size in THUMBNAIL_SIZES:
        size_dir = gallery_root / THUMBNAIL_DIR_NAME / size
        for candidate in (size_dir / new_filename, size_dir / f"{stem}.webp"):
            if candidate.exists():
                raise FileExistsError(f"Target thumbnail already exists: {candidate}")
    return target


def rename_item(
    item: GalleryItem,
    new_filename: str,
    *,
    gallery_root: Path,
) -> RenameReport:
    """Atomically rename the image + thumbnails for ``item``.

    On any failure mid-rename, the helper rolls back every successful
    rename in reverse order before re-raising.  Metadata fields on
    ``item`` are only updated after every on-disk rename succeeds.
    """

    old_filename = item.filename
    if old_filename == new_filename:
        return RenameReport(
            item_id=item.id,
            old_filename=old_filename,
            new_filename=new_filename,
            renamed_paths=[],
        )

    target_image = _check_rename_target(gallery_root, new_filename)
    source_image = _safe_image_path(gallery_root, old_filename)
    if not source_image.exists():
        raise FileNotFoundError(f"Source image missing: {source_image}")

    pairs: list[tuple[Path, Path]] = [(source_image, target_image)]
    thumbs_root = gallery_root / THUMBNAIL_DIR_NAME
    new_stem = Path(new_filename).stem
    for size in THUMBNAIL_SIZES:
        size_dir = thumbs_root / size
        old_same = size_dir / old_filename
        old_webp = size_dir / f"{Path(old_filename).stem}.webp"
        if old_same.exists():
            pairs.append((old_same, size_dir / new_filename))
        if old_webp.exists() and old_webp != old_same:
            pairs.append((old_webp, size_dir / f"{new_stem}.webp"))

    completed: list[tuple[Path, Path]] = []
    try:
        for src, dst in pairs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            completed.append((src, dst))
    except OSError:
        for src, dst in reversed(completed):
            with contextlib.suppress(OSError):
                dst.rename(src)
        raise

    # All on-disk renames succeeded; update typed metadata fields.
    item.filename = new_filename
    if item.thumbnail:
        item.thumbnail = item.thumbnail.replace(old_filename, new_filename)
    new_thumbs: dict[str, str] = {}
    for size, rel in item.thumbnails.items():
        new_thumbs[size] = rel.replace(old_filename, new_filename).replace(
            f"{Path(old_filename).stem}.webp", f"{new_stem}.webp"
        )
    item.thumbnails = new_thumbs

    return RenameReport(
        item_id=item.id,
        old_filename=old_filename,
        new_filename=new_filename,
        renamed_paths=completed,
    )


# ---------------------------------------------------------------------------
# Stats / dedupe / verify / prune
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GalleryStats:
    """Aggregate gallery statistics."""

    total_items: int
    tagged_items: int
    untagged_items: int
    distinct_tags: int
    top_tags: list[tuple[str, int]]
    earliest: float | None
    latest: float | None
    total_image_bytes: int


def compute_stats(
    items: Sequence[GalleryItem],
    *,
    gallery_root: Path,
    top_n: int = 10,
) -> GalleryStats:
    """Compute basic gallery statistics."""

    tag_counter: Counter[str] = Counter()
    tagged = 0
    earliest: float | None = None
    latest: float | None = None
    total_bytes = 0
    images_dir = gallery_root / "images"

    for item in items:
        if item.tags:
            tagged += 1
            tag_counter.update(item.tags)
        if item.created_at is not None:
            if earliest is None or item.created_at < earliest:
                earliest = item.created_at
            if latest is None or item.created_at > latest:
                latest = item.created_at
        if item.filename:
            path = images_dir / item.filename
            with contextlib.suppress(OSError):
                total_bytes += path.stat().st_size

    return GalleryStats(
        total_items=len(items),
        tagged_items=tagged,
        untagged_items=len(items) - tagged,
        distinct_tags=len(tag_counter),
        top_tags=tag_counter.most_common(top_n),
        earliest=earliest,
        latest=latest,
        total_image_bytes=total_bytes,
    )


def format_stats(stats: GalleryStats) -> str:
    """Render :class:`GalleryStats` as a multi-line block."""

    lines = [
        f"total items:       {stats.total_items}",
        f"tagged items:      {stats.tagged_items}",
        f"untagged items:    {stats.untagged_items}",
        f"distinct tags:     {stats.distinct_tags}",
        f"earliest created:  {stats.earliest}",
        f"latest created:    {stats.latest}",
        f"total image bytes: {stats.total_image_bytes}",
    ]
    if stats.top_tags:
        lines.append("top tags:")
        for tag, count in stats.top_tags:
            lines.append(f"  {tag}: {count}")
    return "\n".join(lines)


@dataclass(slots=True)
class DuplicateGroup:
    """A set of items that share the same key."""

    key: str
    kind: str  # "filename" | "checksum"
    items: list[GalleryItem]


def find_duplicates(items: Sequence[GalleryItem]) -> list[DuplicateGroup]:
    """Return groups of items sharing a filename or checksum."""

    groups: list[DuplicateGroup] = []
    by_filename: dict[str, list[GalleryItem]] = {}
    by_checksum: dict[str, list[GalleryItem]] = {}

    for item in items:
        if item.filename:
            by_filename.setdefault(item.filename, []).append(item)
        if item.checksum:
            by_checksum.setdefault(item.checksum, []).append(item)

    for filename, group in by_filename.items():
        if len(group) > 1:
            groups.append(
                DuplicateGroup(key=filename, kind="filename", items=list(group))
            )
    for checksum, group in by_checksum.items():
        if len(group) > 1:
            groups.append(
                DuplicateGroup(key=checksum, kind="checksum", items=list(group))
            )
    return groups


@dataclass(slots=True)
class VerifyReport:
    """Per-item filesystem verification result."""

    item_id: str
    filename: str
    image_present: bool
    missing_thumbnails: list[str]


def verify_items(
    items: Sequence[GalleryItem], *, gallery_root: Path
) -> list[VerifyReport]:
    """Report missing image/thumbnail files for each item."""

    reports: list[VerifyReport] = []
    images_dir = gallery_root / "images"
    for item in items:
        image_path = images_dir / item.filename if item.filename else None
        image_present = bool(image_path and image_path.exists())
        missing: list[str] = []
        for size, rel in (item.thumbnails or {}).items():
            if not (gallery_root / rel).exists():
                missing.append(size)
        if not image_present or missing:
            reports.append(
                VerifyReport(
                    item_id=item.id,
                    filename=item.filename,
                    image_present=image_present,
                    missing_thumbnails=missing,
                )
            )
    return reports


def prune_orphan_thumbnails(
    items: Sequence[GalleryItem], *, gallery_root: Path
) -> list[Path]:
    """Delete thumbnails whose underlying image is no longer in metadata."""

    keep: set[str] = set()
    for item in items:
        if not item.filename:
            continue
        keep.add(item.filename)
        keep.add(f"{Path(item.filename).stem}.webp")

    removed: list[Path] = []
    thumbs_root = gallery_root / THUMBNAIL_DIR_NAME
    if not thumbs_root.is_dir():
        return removed

    for size in THUMBNAIL_SIZES:
        size_dir = thumbs_root / size
        if not size_dir.is_dir():
            continue
        for entry in size_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.name in keep:
                continue
            try:
                entry.unlink()
            except OSError:
                continue
            removed.append(entry)
    return removed


# ---------------------------------------------------------------------------
# Convenience: format helpers used by the CLI layer
# ---------------------------------------------------------------------------


_BYTES_PER_KIB = 1024


def human_bytes(num: int) -> str:
    """Render a byte count as a short human-readable string."""

    size = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < _BYTES_PER_KIB or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= _BYTES_PER_KIB
    return f"{num} B"


__all__ = [
    "DuplicateGroup",
    "GalleryStats",
    "QueryFilters",
    "RemovalReport",
    "RenameReport",
    "VerifyReport",
    "add_tags",
    "compute_stats",
    "delete_thumbnails",
    "find_by_id",
    "find_duplicates",
    "format_export_csv",
    "format_query_ids",
    "format_query_json",
    "format_query_plain",
    "format_show",
    "format_stats",
    "human_bytes",
    "partition_by_ids",
    "prune_orphan_thumbnails",
    "query_items",
    "remove_items",
    "remove_tags",
    "rename_item",
    "set_field",
    "settable_fields",
    "unset_field",
    "verify_items",
]
