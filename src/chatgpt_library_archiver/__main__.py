"""Unified command-line interface for ChatGPT Library Archiver.

This script consolidates the various helper scripts into a single entry
point. By default it downloads new images and regenerates the gallery.
Use the ``bootstrap`` subcommand to create a virtual environment and
install dependencies before running the downloader.

The ``-y/--yes`` flag can be used to automatically answer ``yes`` to any
interactive prompts.
"""

import argparse
import os

from . import bootstrap, gallery, incremental_downloader, tagger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChatGPT Library Archiver")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically answer yes to confirmation prompts.",
    )
    parser.add_argument(
        "--tag-new",
        action="store_true",
        help="Tag newly downloaded images using OpenAI",
    )

    sub = parser.add_subparsers(dest="command")
    boot = sub.add_parser(
        "bootstrap",
        help=(
            "Create a virtual environment, install requirements, "
            "and run the downloader"
        ),
    )
    boot.add_argument(
        "--tag-new", action="store_true", help="Tag newly downloaded images"
    )
    dl = sub.add_parser(
        "download",
        help="Download new images and regenerate the gallery (default)",
    )
    dl.add_argument(
        "--tag-new", action="store_true", help="Tag newly downloaded images"
    )
    sub.add_parser(
        "gallery",
        help="Regenerate gallery without downloading new images",
    )
    tag = sub.add_parser(
        "tag",
        help="Generate or remove tags for images using OpenAI",
    )
    tag.add_argument("--all", action="store_true", help="Re-tag all images")
    tag.add_argument("--ids", nargs="+", help="Tag only specific image IDs")
    tag.add_argument(
        "--remove-all", action="store_true", help="Remove tags from all images"
    )
    tag.add_argument(
        "--remove-ids", nargs="+", help="Remove tags from specific image IDs"
    )
    tag.add_argument("--prompt", help="Override tagging prompt")
    tag.add_argument("--model", help="Override model ID")
    tag.add_argument(
        "--gallery",
        default="gallery",
        help="Path to gallery directory",
    )
    tag.add_argument(
        "--config",
        default="tagging_config.json",
        help="Path to OpenAI tagging configuration",
    )
    tag.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.yes:
        os.environ["ARCHIVER_ASSUME_YES"] = "1"

    if args.command == "bootstrap":
        bootstrap.main(tag_new=args.tag_new)
    elif args.command == "gallery":
        total = gallery.generate_gallery()
        if total:
            print(f"Generated gallery with {total} images.")
        else:
            print("No gallery generated (no images found).")
    elif args.command == "tag":
        count = tagger.main(args)
        if count:
            print(f"Updated tags for {count} images.")
        else:
            print("No images processed.")
    else:
        incremental_downloader.main(tag_new=args.tag_new)


if __name__ == "__main__":
    main()
