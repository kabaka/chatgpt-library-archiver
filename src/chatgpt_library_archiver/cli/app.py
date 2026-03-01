"""Command-line application wiring for the archiver CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .commands.bootstrap import BootstrapCommand
from .commands.download import DownloadCommand
from .commands.extract_auth import ExtractAuthCommand
from .commands.gallery import GalleryCommand
from .commands.import_command import ImportCommand
from .commands.tag import TagCommand


@dataclass
class CLI:
    """Container that owns the argument parser and command dispatch."""

    parser: argparse.ArgumentParser
    default_handler: Callable[[argparse.Namespace], int | None]

    def parse_args(self, argv: Sequence[str] | None = None) -> argparse.Namespace:
        """Parse CLI arguments."""

        return self.parser.parse_args(argv)

    def run(self, args: argparse.Namespace) -> int | None:
        """Execute the handler associated with the parsed arguments."""

        handler: Callable[[argparse.Namespace], int | None] = getattr(
            args, "command_handler", self.default_handler
        )
        return handler(args)


def _register_commands(
    *,
    parser: argparse.ArgumentParser,
    bootstrap_cmd: BootstrapCommand,
    download_cmd: DownloadCommand,
    extract_auth_cmd: ExtractAuthCommand,
    gallery_cmd: GalleryCommand,
    import_cmd: ImportCommand,
    tag_cmd: TagCommand,
) -> Iterable[argparse.ArgumentParser]:
    subparsers = parser.add_subparsers(dest="command")

    registered = []
    registered.append(bootstrap_cmd.register(subparsers))
    download_parser = download_cmd.register(subparsers)
    registered.append(download_parser)
    registered.append(extract_auth_cmd.register(subparsers))
    registered.append(gallery_cmd.register(subparsers))
    registered.append(import_cmd.register(subparsers))
    registered.append(tag_cmd.register(subparsers))

    # ``python -m chatgpt_library_archiver`` should behave like ``download``.
    parser.set_defaults(command_handler=download_cmd.handle, command="download")

    return registered


def create_app(
    *,
    bootstrap_runner: Callable[[bool], int | None],
    download_runner: Callable[..., int | None],
    gallery_generator: Callable[[str], int],
    thumbnail_regenerator: Callable[[str, bool], Iterable[str]],
    import_runner: Callable[..., Iterable[dict]],
    tag_runner: Callable[[argparse.Namespace], int],
    printer: Callable[[str], None] = print,
) -> CLI:
    """Construct the CLI with the provided dependencies."""

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

    bootstrap_cmd = BootstrapCommand(bootstrap_runner)
    download_cmd = DownloadCommand(download_runner)
    extract_auth_cmd = ExtractAuthCommand(printer=printer)
    gallery_cmd = GalleryCommand(
        generate_gallery=gallery_generator,
        regenerate_thumbnails=thumbnail_regenerator,
        printer=printer,
    )
    import_cmd = ImportCommand(
        import_images=import_runner,
        regenerate_thumbnails=thumbnail_regenerator,
        printer=printer,
    )
    tag_cmd = TagCommand(tag_runner=tag_runner, printer=printer)

    _register_commands(
        parser=parser,
        bootstrap_cmd=bootstrap_cmd,
        download_cmd=download_cmd,
        extract_auth_cmd=extract_auth_cmd,
        gallery_cmd=gallery_cmd,
        import_cmd=import_cmd,
        tag_cmd=tag_cmd,
    )

    return CLI(parser=parser, default_handler=download_cmd.handle)
