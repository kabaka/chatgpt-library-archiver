"""Bootstrap command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class BootstrapCommand:
    """Command that prepares the project environment."""

    run_bootstrap: Callable[[bool], int | None]

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

    def handle(self, args: Namespace) -> int | None:
        return self.run_bootstrap(bool(getattr(args, "tag_new", False)))
