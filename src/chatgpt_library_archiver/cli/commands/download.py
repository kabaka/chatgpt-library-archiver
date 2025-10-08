"""Download command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class DownloadCommand:
    """Command that runs the incremental downloader."""

    run_download: Callable[[bool], int | None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "download",
            help="Download new images and regenerate the gallery (default)",
        )
        parser.add_argument(
            "--tag-new", action="store_true", help="Tag newly downloaded images"
        )
        parser.set_defaults(command_handler=self.handle, command="download")
        return parser

    def handle(self, args: Namespace) -> int | None:
        return self.run_download(bool(getattr(args, "tag_new", False)))
