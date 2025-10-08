"""Tag command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from dataclasses import dataclass
from typing import Callable


@dataclass
class TagCommand:
    """Command that manages image tags via OpenAI."""

    tag_runner: Callable[[Namespace], int]
    printer: Callable[[str], None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "tag",
            help="Generate or remove tags for images using OpenAI",
        )
        parser.add_argument("--all", action="store_true", help="Re-tag all images")
        parser.add_argument("--ids", nargs="+", help="Tag only specific image IDs")
        parser.add_argument(
            "--remove-all", action="store_true", help="Remove tags from all images"
        )
        parser.add_argument(
            "--remove-ids", nargs="+", help="Remove tags from specific image IDs"
        )
        parser.add_argument("--prompt", help="Override tagging prompt")
        parser.add_argument("--model", help="Override model ID")
        parser.add_argument(
            "--gallery",
            default="gallery",
            help="Path to gallery directory",
        )
        parser.add_argument(
            "--config",
            default="tagging_config.json",
            help="Path to OpenAI tagging configuration",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="Number of parallel workers",
        )
        parser.set_defaults(command_handler=self.handle, command="tag")
        return parser

    def handle(self, args: Namespace) -> None:
        count = self.tag_runner(args)
        if count:
            self.printer(f"Updated tags for {count} images.")
        else:
            self.printer("No images processed.")
