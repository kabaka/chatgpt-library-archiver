"""Import command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ...metadata import GalleryItem


@dataclass
class ImportCommand:
    """Command that imports local images into the gallery."""

    import_images: Callable[..., Iterable[GalleryItem]]
    regenerate_thumbnails: Callable[[str, bool], Iterable[str]]
    printer: Callable[[str], None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "import",
            help="Import local images into the gallery",
        )
        parser.add_argument(
            "inputs",
            nargs="*",
            help="Image files or directories to import",
        )
        parser.add_argument("--gallery", default="gallery", help="Gallery root path")
        parser.add_argument(
            "--copy",
            action="store_true",
            help="Copy files instead of moving them",
        )
        parser.add_argument(
            "--recursive",
            action="store_true",
            help="Recurse through directories when importing",
        )
        parser.add_argument(
            "--tag",
            dest="tags",
            action="append",
            default=[],
            help="Add tag(s) to imported images (repeatable or comma-separated)",
        )
        parser.add_argument("--title", help="Override title for all imported images")
        parser.add_argument(
            "--conversation-link",
            dest="conversation_links",
            action="append",
            help="Conversation link for each corresponding direct file input",
        )
        parser.add_argument(
            "--tag-new",
            action="store_true",
            help="Tag imported images with OpenAI",
        )
        parser.add_argument(
            "--config",
            default="tagging_config.json",
            help="Path to tagging/AI configuration",
        )
        parser.add_argument(
            "--ai-rename",
            action="store_true",
            help="Use OpenAI to generate descriptive filenames",
        )
        parser.add_argument("--rename-model", help="Model override for AI renaming")
        parser.add_argument("--rename-prompt", help="Prompt override for AI renaming")
        parser.add_argument("--tag-prompt", help="Prompt override for tagging imports")
        parser.add_argument("--tag-model", help="Model override for tagging imports")
        parser.add_argument(
            "--tag-workers",
            type=int,
            default=4,
            help="Worker count when tagging imports",
        )
        parser.add_argument(
            "--no-config-prompt",
            action="store_true",
            help="Fail instead of prompting to create tagging config",
        )
        parser.add_argument(
            "--regenerate-thumbnails",
            action="store_true",
            help="Regenerate thumbnails after import or when run without inputs",
        )
        parser.add_argument(
            "--force-thumbnails",
            action="store_true",
            help="Overwrite thumbnails when regenerating",
        )
        parser.set_defaults(command_handler=self.handle, command="import")
        return parser

    def handle(self, args: Namespace) -> int | None:
        gallery_root = getattr(args, "gallery", "gallery")
        if not getattr(args, "inputs", []):
            if getattr(args, "regenerate_thumbnails", False):
                regenerated = list(
                    self.regenerate_thumbnails(
                        gallery_root=gallery_root,
                        force=bool(getattr(args, "force_thumbnails", False)),
                    )
                )
                if regenerated:
                    self.printer(
                        f"Regenerated thumbnails for {len(regenerated)} images."
                    )
                else:
                    self.printer("No thumbnails regenerated (no images found).")
                return None
            self.printer("No inputs supplied for import.")
            return None

        try:
            imported = list(
                self.import_images(
                    inputs=list(getattr(args, "inputs", [])),
                    gallery_root=gallery_root,
                    copy_files=bool(getattr(args, "copy", False)),
                    recursive=bool(getattr(args, "recursive", False)),
                    tags=list(getattr(args, "tags", []) or []),
                    title=getattr(args, "title", None),
                    conversation_links=self._normalize_sequence(
                        getattr(args, "conversation_links", None)
                    ),
                    tag_new=bool(getattr(args, "tag_new", False)),
                    config_path=getattr(args, "config", "tagging_config.json"),
                    ai_rename=bool(getattr(args, "ai_rename", False)),
                    rename_model=getattr(args, "rename_model", None),
                    rename_prompt=getattr(args, "rename_prompt", None),
                    tag_prompt=getattr(args, "tag_prompt", None),
                    tag_model=getattr(args, "tag_model", None),
                    tag_workers=int(getattr(args, "tag_workers", 4)),
                    allow_interactive=not bool(
                        getattr(args, "no_config_prompt", False)
                    ),
                )
            )
        except ValueError as exc:
            self.printer(str(exc))
            return None

        if getattr(args, "regenerate_thumbnails", False):
            regenerated = list(
                self.regenerate_thumbnails(
                    gallery_root=gallery_root,
                    force=bool(getattr(args, "force_thumbnails", False)),
                )
            )
            if regenerated:
                self.printer(f"Regenerated thumbnails for {len(regenerated)} images.")

        if imported:
            self.printer(f"Imported {len(imported)} images.")
        else:
            self.printer("No images imported.")
        return None

    @staticmethod
    def _normalize_sequence(value: Sequence[str] | None) -> Sequence[str] | None:
        if value is None:
            return None
        return list(value)
