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

from . import bootstrap, gallery, importer, incremental_downloader, tagger


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
    imp = sub.add_parser(
        "import",
        help="Import local images into the gallery",
    )
    imp.add_argument("inputs", nargs="+", help="Image files or directories to import")
    imp.add_argument("--gallery", default="gallery", help="Gallery root path")
    imp.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them",
    )
    imp.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse through directories when importing",
    )
    imp.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Add tag(s) to imported images (repeatable or comma-separated)",
    )
    imp.add_argument("--title", help="Override title for all imported images")
    imp.add_argument(
        "--conversation-link",
        dest="conversation_links",
        action="append",
        help="Conversation link for each corresponding direct file input",
    )
    imp.add_argument(
        "--tag-new",
        action="store_true",
        help="Tag imported images with OpenAI",
    )
    imp.add_argument(
        "--config",
        default="tagging_config.json",
        help="Path to tagging/AI configuration",
    )
    imp.add_argument(
        "--ai-rename",
        action="store_true",
        help="Use OpenAI to generate descriptive filenames",
    )
    imp.add_argument("--rename-model", help="Model override for AI renaming")
    imp.add_argument("--rename-prompt", help="Prompt override for AI renaming")
    imp.add_argument("--tag-prompt", help="Prompt override for tagging imports")
    imp.add_argument("--tag-model", help="Model override for tagging imports")
    imp.add_argument(
        "--tag-workers",
        type=int,
        default=4,
        help="Worker count when tagging imports",
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
    elif args.command == "import":
        imported = importer.import_images(
            inputs=args.inputs,
            gallery_root=args.gallery,
            copy_files=args.copy,
            recursive=args.recursive,
            tags=args.tags,
            title=args.title,
            conversation_links=args.conversation_links,
            tag_new=args.tag_new,
            config_path=args.config,
            ai_rename=args.ai_rename,
            rename_model=args.rename_model,
            rename_prompt=args.rename_prompt,
            tag_prompt=args.tag_prompt,
            tag_model=args.tag_model,
            tag_workers=args.tag_workers,
        )
        if imported:
            print(f"Imported {len(imported)} images.")
        else:
            print("No images imported.")
    else:
        incremental_downloader.main(tag_new=args.tag_new)


if __name__ == "__main__":
    main()
