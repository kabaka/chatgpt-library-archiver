"""Top-level package for ChatGPT Library Archiver."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = [
    "bootstrap",
    "gallery",
    "importer",
    "incremental_downloader",
    "metadata",
    "tag_normalizer",
    "tagger",
    "thumbnails",
    "utils",
]

try:
    __version__ = version("chatgpt-library-archiver")
except PackageNotFoundError:
    __version__ = "0.0.0"
