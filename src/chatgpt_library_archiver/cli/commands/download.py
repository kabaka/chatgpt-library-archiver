"""Download command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class DownloadCommand:
    """Command that runs the incremental downloader."""

    run_download: Callable[..., int | None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "download",
            help="Download new images and regenerate the gallery (default)",
        )
        parser.add_argument(
            "--tag-new", action="store_true", help="Tag newly downloaded images"
        )
        parser.add_argument(
            "--browser",
            choices=["edge", "chrome"],
            default=None,
            help="Use credentials from Edge or Chrome instead of auth.txt (macOS only)",
        )
        parser.add_argument(
            "--max-workers",
            "-w",
            type=int,
            default=6,
            help="Maximum number of concurrent download threads (default: 6)",
        )
        parser.set_defaults(command_handler=self.handle, command="download")
        return parser

    def handle(self, args: Namespace) -> int | None:
        max_workers = max(1, int(getattr(args, "max_workers", 6)))
        return self.run_download(
            bool(getattr(args, "tag_new", False)),
            browser=getattr(args, "browser", None),
            max_workers=max_workers,
        )
