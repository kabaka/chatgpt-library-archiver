"""Unified command-line interface for ChatGPT Library Archiver."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from . import bootstrap, gallery, importer, incremental_downloader, tagger
from .cli import CLI, create_app


def build_app(*, printer: Callable[[str], None] = print) -> CLI:
    """Create the CLI wired up with the production dependencies."""

    return create_app(
        bootstrap_runner=bootstrap.main,
        download_runner=incremental_downloader.main,
        gallery_generator=gallery.generate_gallery,
        thumbnail_regenerator=importer.regenerate_thumbnails,
        import_runner=importer.import_images,
        tag_runner=tagger.tag_images,
        printer=printer,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    printer: Callable[[str], None] = print,
) -> int | None:
    """Entrypoint for ``python -m chatgpt_library_archiver``."""

    app = build_app(printer=printer)
    args = app.parse_args(argv)

    if getattr(args, "yes", False):
        os.environ["ARCHIVER_ASSUME_YES"] = "1"

    return app.run(args)


if __name__ == "__main__":
    main()
