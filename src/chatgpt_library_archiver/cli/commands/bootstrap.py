"""Bootstrap command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class BootstrapCommand:
    """Command that prepares the project environment."""

    run_bootstrap: Callable[[bool], Optional[int]]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "bootstrap",
            help=(
                "Create a virtual environment, install requirements, "
                "and run the downloader"
            ),
        )
        parser.add_argument(
            "--tag-new", action="store_true", help="Tag newly downloaded images"
        )
        parser.set_defaults(command_handler=self.handle, command="bootstrap")
        return parser

    def handle(self, args: Namespace) -> Optional[int]:
        return self.run_bootstrap(bool(getattr(args, "tag_new", False)))
