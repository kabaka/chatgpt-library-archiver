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

from . import bootstrap, incremental_downloader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChatGPT Library Archiver")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically answer yes to confirmation prompts.",
    )

    sub = parser.add_subparsers(dest="command")
    sub.add_parser(
        "bootstrap",
        help="Create a virtual environment, install requirements, and run the downloader",
    )
    sub.add_parser(
        "download",
        help="Download new images and regenerate the gallery (default)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.yes:
        os.environ["ARCHIVER_ASSUME_YES"] = "1"

    if args.command == "bootstrap":
        bootstrap.main()
    else:
        incremental_downloader.main()


if __name__ == "__main__":
    main()

