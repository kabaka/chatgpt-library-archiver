# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- This project uses conventional commit prefixes (feat:, fix:, chore:, docs:).
     Future releases may adopt automated changelog generation from commit history
     (e.g., via git-cliff or python-semantic-release). -->

## [Unreleased]

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
