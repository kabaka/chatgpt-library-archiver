"""Gallery command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from dataclasses import dataclass
from typing import Callable, Iterable, Optional


@dataclass
class GalleryCommand:
    """Command that regenerates the gallery HTML and thumbnails."""

    generate_gallery: Callable[[str], int]
    regenerate_thumbnails: Callable[[str, bool], Iterable[str]]
    printer: Callable[[str], None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "gallery", help="Regenerate gallery without downloading new images"
        )
        parser.add_argument("--gallery", default="gallery", help="Gallery root path")
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
        parser.set_defaults(command_handler=self.handle, command="gallery")
        return parser

    def handle(self, args: Namespace) -> Optional[int]:
        gallery_root = getattr(args, "gallery", "gallery")
        if getattr(args, "regenerate_thumbnails", False):
            regenerated = list(
                self.regenerate_thumbnails(
                    gallery_root=gallery_root,
                    force=bool(getattr(args, "force_thumbnails", False)),
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
