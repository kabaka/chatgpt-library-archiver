"""Gallery command implementation with verb-based subcommand dispatch.

The ``gallery`` command is a small router over a set of verbs:

  * ``build``       - regenerate ``index.html`` (legacy default).
  * ``query``       - list items matching filters.
  * ``show``        - pretty-print a single item.
  * ``tag``         - add tags to an item.
  * ``untag``       - remove tags from an item.
  * ``set``         - update typed fields.
  * ``unset``       - clear a typed/extra field.
  * ``rm``          - delete entries (metadata + on-disk files).
  * ``mv``          - atomic rename of image + thumbnails.
  * ``stats``       - print gallery aggregates.
  * ``export``      - emit metadata as JSON or CSV.
  * ``affinity``    - recompute ``affinity_index`` only.
  * ``dedupe``      - report duplicate filenames / checksums.
  * ``verify``      - report missing image / thumbnail files.
  * ``prune-thumbs``- delete orphaned thumbnail files.

Bare ``gallery`` (no verb) preserves the historical behaviour and aliases
to ``gallery build``.
"""

from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ... import management
from ...affinity import compute_affinity_indices
from ...metadata import GalleryItem, load_gallery_items, save_gallery_items
from ...utils import ASSUME_YES_ENV


@dataclass
class GalleryCommand:
    """Command that manages the static gallery and its metadata."""

    generate_gallery: Callable[..., int]
    regenerate_thumbnails: Callable[..., Iterable[str]]
    printer: Callable[[str], None]

    # ------------------------------------------------------------------
    # Argparse registration
    # ------------------------------------------------------------------
    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "gallery",
            help="Manage the static gallery (build, query, mutate, inspect)",
            description=(
                "Manage the static gallery. Run `gallery <verb> --help` for "
                "the options of each verb. Bare `gallery` aliases `build`."
            ),
        )
        parser.set_defaults(
            command_handler=self.handle,
            command="gallery",
            gallery_verb=None,
            gallery_handler=self._handle_build,
        )
        # Build's flags must also be valid on the bare `gallery` invocation
        # so existing users (and our test suite) can still pass
        # `--gallery DIR` / `--regenerate-thumbnails` / `--force-thumbnails`
        # / `--webp-thumbnails` without specifying the `build` verb.
        self._add_build_flags(parser)

        verbs = parser.add_subparsers(dest="gallery_verb", required=False)
        self._add_build(verbs)
        self._add_query(verbs)
        self._add_show(verbs)
        self._add_tag(verbs)
        self._add_untag(verbs)
        self._add_set(verbs)
        self._add_unset(verbs)
        self._add_rm(verbs)
        self._add_mv(verbs)
        self._add_stats(verbs)
        self._add_export(verbs)
        self._add_affinity(verbs)
        self._add_dedupe(verbs)
        self._add_verify(verbs)
        self._add_prune_thumbs(verbs)
        return parser

    # ------------------------------------------------------------------
    # Top-level dispatcher
    # ------------------------------------------------------------------
    def handle(self, args: Namespace) -> int | None:
        handler: Callable[[Namespace], int | None] = getattr(
            args, "gallery_handler", self._handle_build
        )
        return handler(args)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _gallery_root(args: Namespace) -> str:
        return getattr(args, "gallery", "gallery")

    def _load(self, args: Namespace) -> list[GalleryItem]:
        return load_gallery_items(self._gallery_root(args))

    def _save(self, args: Namespace, items: Iterable[GalleryItem]) -> None:
        item_list = list(items)
        compute_affinity_indices(item_list)
        save_gallery_items(self._gallery_root(args), item_list)

    @staticmethod
    def _add_gallery_arg(parser: ArgumentParser) -> None:
        parser.add_argument("--gallery", default="gallery", help="Gallery root path")

    def _yes(self, args: Namespace) -> bool:
        if getattr(args, "yes", False):
            return True
        return os.environ.get(ASSUME_YES_ENV, "").lower() in {"1", "true", "yes"}

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------
    def _add_build_flags(self, parser: ArgumentParser) -> None:
        self._add_gallery_arg(parser)
        parser.add_argument(
            "--regenerate-thumbnails",
            action="store_true",
            help="Ensure thumbnails exist before writing the gallery",
        )
        parser.add_argument(
            "--force-thumbnails",
            action="store_true",
            help="Overwrite thumbnails when regenerating",
        )
        parser.add_argument(
            "--webp-thumbnails",
            action="store_true",
            help="Generate thumbnails in WebP format for smaller file sizes",
        )

    def _add_build(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser(
            "build", help="Rebuild gallery index.html and recompute affinity"
        )
        self._add_build_flags(p)
        p.set_defaults(gallery_handler=self._handle_build)

    def _handle_build(self, args: Namespace) -> int | None:
        gallery_root = self._gallery_root(args)
        if getattr(args, "regenerate_thumbnails", False):
            regenerated = list(
                self.regenerate_thumbnails(
                    gallery_root=gallery_root,
                    force=bool(getattr(args, "force_thumbnails", False)),
                    webp=bool(getattr(args, "webp_thumbnails", False)),
                )
            )
            if regenerated:
                self.printer(f"Generated thumbnails for {len(regenerated)} images.")
            else:
                self.printer("No thumbnails regenerated (no images found).")
        total = self.generate_gallery(gallery_root=gallery_root)
        if total:
            self.printer(f"Generated gallery with {total} images.")
        else:
            self.printer("No gallery generated (no images found).")
        return None

    # ------------------------------------------------------------------
    # query / export filters
    # ------------------------------------------------------------------
    def _add_query_filter_args(self, parser: ArgumentParser) -> None:
        parser.add_argument("--id", action="append", default=[], help="Match item id")
        parser.add_argument(
            "--tag", action="append", default=[], help="Require tag (repeatable)"
        )
        parser.add_argument(
            "--no-tag",
            action="append",
            default=[],
            help="Exclude tag (repeatable)",
        )
        parser.add_argument("--title-contains", help="Substring match on title")
        parser.add_argument("--prompt-contains", help="Substring match on prompt")
        parser.add_argument("--filename-contains", help="Substring match on filename")
        parser.add_argument(
            "--created-after",
            "--since",
            dest="created_after",
            type=float,
            help="Only items with created_at >= TS (epoch seconds)",
        )
        parser.add_argument(
            "--created-before",
            "--until",
            dest="created_before",
            type=float,
            help="Only items with created_at <= TS (epoch seconds)",
        )
        parser.add_argument(
            "--has-thumbnail",
            action="store_true",
            help="Only items with at least one thumbnail entry",
        )
        parser.add_argument(
            "--missing-thumbnail",
            action="store_true",
            help="Only items with no thumbnail entries",
        )
        parser.add_argument(
            "--has-tags",
            action="store_true",
            help="Only items with at least one tag",
        )
        parser.add_argument(
            "--no-tags",
            action="store_true",
            help="Only items with no tags",
        )
        parser.add_argument(
            "--has-prompt",
            action="store_true",
            help="Only items with a non-empty prompt",
        )
        parser.add_argument(
            "--no-prompt",
            action="store_true",
            help="Only items with no prompt",
        )
        parser.add_argument(
            "--conversation-id",
            help="Only items whose conversation_id equals this value",
        )
        parser.add_argument(
            "--missing-file",
            action="store_true",
            help="Only items whose image file is missing on disk",
        )
        parser.add_argument(
            "--extra",
            action="append",
            default=[],
            metavar="KEY=VALUE",
            help="Match item.extra[KEY] == VALUE (repeatable)",
        )
        parser.add_argument("--limit", type=int, help="Cap result count")

    def _build_filters(self, args: Namespace) -> management.QueryFilters:
        extras: list[tuple[str, str]] = []
        for raw in getattr(args, "extra", None) or []:
            if "=" not in raw:
                raise SystemExit(f"--extra expects KEY=VALUE, got: {raw!r}")
            key, value = raw.split("=", 1)
            extras.append((key, value))

        if getattr(args, "has_thumbnail", False) and getattr(
            args, "missing_thumbnail", False
        ):
            raise SystemExit(
                "Specify at most one of --has-thumbnail / --missing-thumbnail"
            )
        has_thumbnail: bool | None = None
        if getattr(args, "has_thumbnail", False):
            has_thumbnail = True
        elif getattr(args, "missing_thumbnail", False):
            has_thumbnail = False

        if getattr(args, "has_tags", False) and getattr(args, "no_tags", False):
            raise SystemExit("Specify at most one of --has-tags / --no-tags")
        has_tags: bool | None = None
        if getattr(args, "has_tags", False):
            has_tags = True
        elif getattr(args, "no_tags", False):
            has_tags = False

        if getattr(args, "has_prompt", False) and getattr(args, "no_prompt", False):
            raise SystemExit("Specify at most one of --has-prompt / --no-prompt")
        has_prompt: bool | None = None
        if getattr(args, "has_prompt", False):
            has_prompt = True
        elif getattr(args, "no_prompt", False):
            has_prompt = False

        return management.QueryFilters(
            ids=list(getattr(args, "id", []) or []),
            tags=list(getattr(args, "tag", []) or []),
            excluded_tags=list(getattr(args, "no_tag", []) or []),
            title_contains=getattr(args, "title_contains", None),
            prompt_contains=getattr(args, "prompt_contains", None),
            filename_contains=getattr(args, "filename_contains", None),
            created_after=getattr(args, "created_after", None),
            created_before=getattr(args, "created_before", None),
            has_thumbnail=has_thumbnail,
            has_tags=has_tags,
            has_prompt=has_prompt,
            conversation_id=getattr(args, "conversation_id", None),
            missing_file=bool(getattr(args, "missing_file", False)),
            gallery_root=Path(self._gallery_root(args)),
            extra=extras,
            limit=getattr(args, "limit", None),
        )

    def _add_query(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("query", help="List items matching filters")
        self._add_gallery_arg(p)
        self._add_query_filter_args(p)
        p.add_argument(
            "--format",
            choices=("plain", "json", "ids"),
            default="plain",
            help="Output format (plain table, JSON array, or newline-delimited ids)",
        )
        p.add_argument(
            "--sort",
            choices=("created", "title", "filename", "affinity"),
            default=None,
            help="Sort matched items by this field (nulls sort last)",
        )
        p.add_argument(
            "--reverse",
            action="store_true",
            help="Reverse the sort order (only meaningful with --sort)",
        )
        p.set_defaults(gallery_handler=self._handle_query)

    def _handle_query(self, args: Namespace) -> int | None:
        items = self._load(args)
        filters = self._build_filters(args)
        results = management.query_items(
            items,
            filters,
            sort=getattr(args, "sort", None),
            reverse=bool(getattr(args, "reverse", False)),
        )
        fmt = getattr(args, "format", "plain")
        if fmt == "json":
            self.printer(management.format_query_json(results))
        elif fmt == "ids":
            self.printer(management.format_query_ids(results))
        else:
            self.printer(management.format_query_plain(results))
        return None

    # ------------------------------------------------------------------
    # show
    # ------------------------------------------------------------------
    def _add_show(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("show", help="Print full metadata for a single item")
        self._add_gallery_arg(p)
        p.add_argument("id", help="Item id to display")
        p.add_argument(
            "--json", action="store_true", help="Render as JSON instead of pretty"
        )
        p.set_defaults(gallery_handler=self._handle_show)

    def _handle_show(self, args: Namespace) -> int | None:
        items = self._load(args)
        item = management.find_by_id(items, args.id)
        if item is None:
            self.printer(f"No item with id={args.id!r}")
            return 1
        self.printer(management.format_show(item, as_json=bool(args.json)))
        return None

    # ------------------------------------------------------------------
    # tag / untag
    # ------------------------------------------------------------------
    def _add_tag(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("tag", help="Add tags to an item")
        self._add_gallery_arg(p)
        p.add_argument("id", help="Item id")
        p.add_argument("tags", nargs="+", help="Tag(s) to add")
        p.set_defaults(gallery_handler=self._handle_tag_add)

    def _handle_tag_add(self, args: Namespace) -> int | None:
        items = self._load(args)
        item = management.find_by_id(items, args.id)
        if item is None:
            self.printer(f"No item with id={args.id!r}")
            return 1
        added = management.add_tags(item, args.tags)
        self._save(args, items)
        self.printer(f"Added {added} tag(s) to {args.id} (now: {item.tags})")
        return None

    def _add_untag(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("untag", help="Remove tags from an item")
        self._add_gallery_arg(p)
        p.add_argument("id", help="Item id")
        p.add_argument("tags", nargs="+", help="Tag(s) to remove")
        p.set_defaults(gallery_handler=self._handle_tag_remove)

    def _handle_tag_remove(self, args: Namespace) -> int | None:
        items = self._load(args)
        item = management.find_by_id(items, args.id)
        if item is None:
            self.printer(f"No item with id={args.id!r}")
            return 1
        removed = management.remove_tags(item, args.tags)
        self._save(args, items)
        self.printer(f"Removed {removed} tag(s) from {args.id} (now: {item.tags})")
        return None

    # ------------------------------------------------------------------
    # set / unset
    # ------------------------------------------------------------------
    def _add_set(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("set", help="Set typed fields on an item")
        self._add_gallery_arg(p)
        p.add_argument("id", help="Item id")
        for field_name in management.settable_fields():
            p.add_argument(
                f"--{field_name.replace('_', '-')}",
                dest=field_name,
                help=f"Set the {field_name!r} field",
            )
        p.set_defaults(gallery_handler=self._handle_set)

    def _handle_set(self, args: Namespace) -> int | None:
        items = self._load(args)
        item = management.find_by_id(items, args.id)
        if item is None:
            self.printer(f"No item with id={args.id!r}")
            return 1
        applied: list[str] = []
        for field_name in management.settable_fields():
            value = getattr(args, field_name, None)
            if value is None:
                continue
            management.set_field(item, field_name, value)
            applied.append(field_name)
        if not applied:
            self.printer("No fields supplied; nothing to do.")
            return 0
        self._save(args, items)
        self.printer(f"Updated {applied} on {args.id}")
        return None

    def _add_unset(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("unset", help="Clear a field on an item")
        self._add_gallery_arg(p)
        p.add_argument("id", help="Item id")
        p.add_argument("field", help="Field name to clear (typed field or extra key)")
        p.set_defaults(gallery_handler=self._handle_unset)

    def _handle_unset(self, args: Namespace) -> int | None:
        items = self._load(args)
        item = management.find_by_id(items, args.id)
        if item is None:
            self.printer(f"No item with id={args.id!r}")
            return 1
        try:
            management.unset_field(item, args.field)
        except KeyError as exc:
            self.printer(str(exc))
            return 1
        self._save(args, items)
        self.printer(f"Cleared {args.field!r} on {args.id}")
        return None

    # ------------------------------------------------------------------
    # rm
    # ------------------------------------------------------------------
    def _add_rm(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser(
            "rm",
            help="Delete items (metadata + image file + thumbnails)",
        )
        self._add_gallery_arg(p)
        p.add_argument("ids", nargs="+", help="Item id(s) to remove")
        p.add_argument(
            "--yes",
            action="store_true",
            help="Skip the confirmation prompt",
        )
        p.set_defaults(gallery_handler=self._handle_rm)

    def _handle_rm(self, args: Namespace) -> int | None:
        items = self._load(args)
        matched, missing = management.partition_by_ids(items, args.ids)
        if missing:
            self.printer(f"Unknown id(s): {missing}")
        if not matched:
            return 1 if missing else 0

        if not self._yes(args):
            self.printer(
                f"Refusing to delete {len(matched)} item(s) without --yes "
                "(or set ARCHIVER_ASSUME_YES=1)."
            )
            return 1

        survivors, reports = management.remove_items(
            list(items),
            [item.id for item in matched],
            gallery_root=Path(self._gallery_root(args)),
        )
        self._save(args, survivors)
        for report in reports:
            self.printer(
                f"rm {report.item_id}: image_removed={report.image_removed} "
                f"thumbnails_removed={report.thumbnails_removed} "
                f"error={report.error}"
            )
        return None

    # ------------------------------------------------------------------
    # mv
    # ------------------------------------------------------------------
    def _add_mv(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser(
            "mv",
            help="Rename image + thumbnails atomically; updates metadata",
        )
        self._add_gallery_arg(p)
        p.add_argument("id", help="Item id")
        p.add_argument("new_filename", help="New basename inside images/")
        p.set_defaults(gallery_handler=self._handle_mv)

    def _handle_mv(self, args: Namespace) -> int | None:
        items = self._load(args)
        item = management.find_by_id(items, args.id)
        if item is None:
            self.printer(f"No item with id={args.id!r}")
            return 1
        try:
            report = management.rename_item(
                item,
                args.new_filename,
                gallery_root=Path(self._gallery_root(args)),
            )
        except (FileExistsError, FileNotFoundError, ValueError, OSError) as exc:
            self.printer(f"mv failed: {exc}")
            return 1
        self._save(args, items)
        self.printer(
            f"Renamed {report.old_filename} -> {report.new_filename} "
            f"({len(report.renamed_paths)} path(s))"
        )
        return None

    # ------------------------------------------------------------------
    # stats
    # ------------------------------------------------------------------
    def _add_stats(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("stats", help="Print gallery summary statistics")
        self._add_gallery_arg(p)
        p.add_argument(
            "--top", type=int, default=10, help="Number of top tags to display"
        )
        p.set_defaults(gallery_handler=self._handle_stats)

    def _handle_stats(self, args: Namespace) -> int | None:
        items = self._load(args)
        stats = management.compute_stats(
            items,
            gallery_root=Path(self._gallery_root(args)),
            top_n=int(args.top),
        )
        self.printer(management.format_stats(stats))
        self.printer(
            f"total image size:  {management.human_bytes(stats.total_image_bytes)}"
        )
        return None

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    def _add_export(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("export", help="Export metadata to JSON or CSV")
        self._add_gallery_arg(p)
        p.add_argument(
            "--format", choices=("json", "csv"), default="json", help="Output format"
        )
        p.set_defaults(gallery_handler=self._handle_export)

    def _handle_export(self, args: Namespace) -> int | None:
        items = self._load(args)
        if args.format == "csv":
            self.printer(management.format_export_csv(items))
        else:
            self.printer(management.format_query_json(items))
        return None

    # ------------------------------------------------------------------
    # affinity
    # ------------------------------------------------------------------
    def _add_affinity(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser(
            "affinity", help="Recompute affinity_index only; do not rebuild HTML"
        )
        self._add_gallery_arg(p)
        p.set_defaults(gallery_handler=self._handle_affinity)

    def _handle_affinity(self, args: Namespace) -> int | None:
        items = self._load(args)
        compute_affinity_indices(items)
        save_gallery_items(self._gallery_root(args), items)
        self.printer(f"Recomputed affinity for {len(items)} item(s).")
        return None

    # ------------------------------------------------------------------
    # dedupe
    # ------------------------------------------------------------------
    def _add_dedupe(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser("dedupe", help="Report duplicate filenames or checksums")
        self._add_gallery_arg(p)
        p.set_defaults(gallery_handler=self._handle_dedupe)

    def _handle_dedupe(self, args: Namespace) -> int | None:
        items = self._load(args)
        groups = management.find_duplicates(items)
        if not groups:
            self.printer("No duplicates found.")
            return 0
        for group in groups:
            ids = [it.id for it in group.items]
            self.printer(f"{group.kind}={group.key!r}: {ids}")
        return None

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------
    def _add_verify(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser(
            "verify",
            help="Report items with missing image files or thumbnails",
        )
        self._add_gallery_arg(p)
        p.set_defaults(gallery_handler=self._handle_verify)

    def _handle_verify(self, args: Namespace) -> int | None:
        items = self._load(args)
        reports = management.verify_items(
            items, gallery_root=Path(self._gallery_root(args))
        )
        if not reports:
            self.printer("All items present.")
            return 0
        for report in reports:
            self.printer(
                f"{report.item_id} ({report.filename}): "
                f"image_present={report.image_present} "
                f"missing_thumbnails={report.missing_thumbnails}"
            )
        return None

    # ------------------------------------------------------------------
    # prune-thumbs
    # ------------------------------------------------------------------
    def _add_prune_thumbs(self, verbs: _SubParsersAction[ArgumentParser]) -> None:
        p = verbs.add_parser(
            "prune-thumbs",
            help="Delete thumbnail files with no matching metadata entry",
        )
        self._add_gallery_arg(p)
        p.set_defaults(gallery_handler=self._handle_prune)

    def _handle_prune(self, args: Namespace) -> int | None:
        items = self._load(args)
        removed = management.prune_orphan_thumbnails(
            items, gallery_root=Path(self._gallery_root(args))
        )
        if not removed:
            self.printer("No orphaned thumbnails found.")
            return 0
        for path in removed:
            self.printer(f"removed: {path}")
        self.printer(f"Removed {len(removed)} orphaned thumbnail(s).")
        return None
