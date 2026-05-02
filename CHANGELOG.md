# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- This project uses conventional commit prefixes (feat:, fix:, chore:, docs:).
     Future releases may adopt automated changelog generation from commit history
     (e.g., via git-cliff or python-semantic-release). -->

## [Unreleased]

### Added

- **Gallery management subcommands** — the `gallery` command is now a
  verb-based router exposing `build`, `query`, `show`, `tag`, `untag`, `set`,
  `unset`, `rm`, `mv`, `stats`, `export`, `affinity`, `dedupe`, `verify`, and
  `prune-thumbs`. Bare `gallery` continues to alias `gallery build` for
  backwards compatibility. `rm` deletes are gated behind `--yes` or
  `ARCHIVER_ASSUME_YES=1`; `mv` validates the target before renaming and rolls
  back on failure.
- `--thumb-workers N` flag on `download` and `import` controlling the
  thumbnail `ProcessPoolExecutor` size (default `min(cpu_count, 8)`).
  Thumbnail generation now runs in parallel across the download, import, and
  regenerate pipelines.
- Tag affinity sort mode in the gallery viewer. A precomputed
  `affinity_index` field is written to `metadata.json` during `gallery build`
  / `gallery affinity`; the viewer exposes it as the new "Tag similarity"
  sort option, and `gallery query --sort=affinity` consumes it from the CLI.

### Changed

- Gallery metadata is now embedded directly into `index.html` at generation
  time. The gallery can be opened by double-clicking the file — no HTTP server
  is required.
- On touch devices, the hover-overlay metadata strip is suppressed under
  `(hover: none) and (pointer: coarse)` and replaced by a long-press metadata
  modal. A normal tap continues to open the lightbox.

### Fixed

- `chatgpt-archiver --yes` no longer leaks `ARCHIVER_ASSUME_YES=1` into the
  caller's environment after the command returns; the variable is restored to
  its previous value once `main()` exits.
- Mobile thumbnail sizing: selecting Medium or Large sizes now loads appropriately
  sized images instead of always showing small thumbnails.
- `tag --tag-new` no longer overwrites user-supplied tags. Existing tags are
  merged with AI-generated tags, deduplicated by normalized form, and order
  is preserved (existing tags first, new AI tags appended).
- `gallery-full` size in the gallery viewer now serves the original image at
  high DPI via `srcset` instead of the 400 px `large` thumbnail.
- Pinch-to-zoom in the lightbox no longer closes it on mobile. The viewer
  was rewritten on Pointer Events with multi-touch latching so only a
  single-pointer tap dismisses it.

## [0.1.0] — 2026-03-01

### Added

- **Image downloading** from ChatGPT conversations with incremental download
  support (skip already-archived files).
- **Static HTML gallery** — single-page viewer with search, date-range
  filtering, tag filtering, keyboard navigation, dark mode, and responsive
  layout.
- **AI-powered image tagging** via OpenAI vision API (`responses.create`) with
  configurable model, prompt, and automatic file renaming.
- **Thumbnail generation** at three sizes (small / medium / large) using Pillow,
  with EXIF orientation correction.
- **Browser cookie extraction** (`extract-auth`) for automatic credential
  retrieval from Chrome and Edge on macOS.
- **Bootstrap command** — one-command setup that detects or creates a virtual
  environment and installs dependencies via `uv`, `pip-tools`, or `pip`.
- **CLI interface** with subcommands: `download`, `gallery`, `tag`,
  `extract-auth`, `import`, and `bootstrap`.
- `metadata.json` tracking per-image metadata (title, creation date, tags,
  download URL, dimensions).
- Makefile with `install`, `lint`, `test`, and `build` targets.
- GitHub Actions CI pipeline (lint + test on every PR and push to `main`).
- Pre-commit hooks for formatting and linting.
- 85 % minimum test coverage gate enforced via `pytest-cov`.

[Unreleased]: https://github.com/kabaka/chatgpt-library-archiver/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kabaka/chatgpt-library-archiver/releases/tag/v0.1.0
