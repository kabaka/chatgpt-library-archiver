"""Tag command implementation."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class TagCommand:
    """Command that manages image tags via OpenAI."""

    tag_runner: Callable[..., int]
    tag_remover: Callable[..., int]
    printer: Callable[[str], None]

    def register(self, subparsers: _SubParsersAction[ArgumentParser]) -> ArgumentParser:
        parser = subparsers.add_parser(
            "tag",
            help="Generate or remove tags for images using OpenAI",
            description=(
                "Generate or remove tags for images using the OpenAI vision API. "
                "When generating tags, images are sent to OpenAI as base64-encoded "
                "payloads for analysis. Review OpenAI's API data usage policy at "
                "https://openai.com/policies/api-data-usage-policies before use."
            ),
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
            "--no-config-prompt",
            action="store_true",
            help="Fail if the tagging config is missing",
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
        remove_all = getattr(args, "remove_all", False)
        remove_ids = getattr(args, "remove_ids", None)

        if remove_all or remove_ids:
            count = self.tag_remover(
                gallery_root=getattr(args, "gallery", "gallery"),
                ids=remove_ids,
            )
        else:
            re_tag = getattr(args, "all", False) or bool(getattr(args, "ids", None))
            count = self.tag_runner(
                gallery_root=getattr(args, "gallery", "gallery"),
                ids=getattr(args, "ids", None),
                re_tag=re_tag,
                config_path=getattr(args, "config", "tagging_config.json"),
                prompt=getattr(args, "prompt", None),
                model=getattr(args, "model", None),
                max_workers=int(getattr(args, "workers", 4)),
                allow_interactive=not bool(getattr(args, "no_config_prompt", False)),
            )

        if count:
            self.printer(f"Updated tags for {count} images.")
        else:
            self.printer("No images processed.")
