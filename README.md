# ChatGPT Library Archiver

This is a Python-based toolset for downloading, archiving, and browsing images from the ChatGPT image library. It stores all images in a single folder and generates static HTML galleries for easy viewing.

See [DISCLAIMER.md](DISCLAIMER.md) for important legal notices.

---

## ⚠️ Note

Support for legacy versioned gallery folders (`v1`, `v2`, etc.) has been removed.
If you're upgrading from an older release that used those directories, re-download
your images with this version or run a previous release to migrate your data.

## 📦 Folder Structure

```
gallery/
├── images/
├── thumbs/
│   ├── small/
│   ├── medium/
│   └── large/
├── metadata.json
└── index.html  ← single-page gallery
auth.txt        ← credentials for API access
tagging_config.json ← OpenAI API key, model, and prompt for tagging
```

---

## ⚙️ 1. Setup Instructions

### 🔹 Requirements

- Python 3.10+
- Internet connection
- Your browser access to [chat.openai.com](https://chat.openai.com)

### 🔹 Install Dependencies

Recommended: use a virtual environment.

Option A — one command bootstrap (detects/creates env, installs deps, runs):

```
python -m chatgpt_library_archiver bootstrap
```

The bootstrapper reuses an activated virtual environment, otherwise it creates
`.venv` for you. It prefers [`uv`](https://github.com/astral-sh/uv) or
[`pip-tools`](https://github.com/jazzband/pip-tools) when available to perform a
deterministic sync of `requirements*.txt`, falling back to `pip install` if
neither tool is present.

Option B — manual setup:

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
pre-commit install --install-hooks
```

The `Makefile` includes dedicated targets so you can choose the dependency
installer that matches your automation environment:

```
make deps-pip        # pip install -e .[dev]
make deps-pip-tools  # pip-sync requirements*.txt, then install package editable
make deps-uv         # uv pip sync requirements*.txt, then install package editable
make install         # default deps (pip) + pre-commit hook installation
```

`make deps` is aliased to `deps-pip` for local development, while CI/CD can pick
the appropriate `deps-*` target to ensure deterministic provisioning.

### 🔍 Quality gates

Run the following targets locally before opening a pull request to match the
project's continuous integration pipeline:

```bash
make lint  # ruff linting & formatting checks plus strict Pyright type analysis
make test  # pytest with coverage; fails below 85% project coverage
```

CI enforces these same commands to guarantee formatting convergence, modern Ruff
rule sets (including `PL`, `RUF`, and `FURB`), strict static typing, and minimum
test coverage.

---

## 🛠 2. `auth.txt` — Setup Your Authentication

This file is required for authenticated API access. You can either let the tool prompt you interactively on first run, or create it manually. Here's what it must contain if creating manually:

```
url=https://chat.openai.com/backend-api/my/recent/image_gen?limit=100
authorization=Bearer <your_token_here>
cookie=__Secure-next-auth.session-token=<your_cookie_here>
referer=https://chat.openai.com/library
user_agent=Mozilla/5.0 (...)
oai_client_version=...
oai_device_id=...
oai_language=...
```

### How to Get These:
1. Log into [https://chat.openai.com/library](https://chat.openai.com/library)
2. Open Developer Tools (in Chrome, by pressing F12) → Network tab → Fetch/XHR
3. Scroll down the page to load new images in the library
4. Find any request to `image_gen` : they should look like `image_gen?limit=6&after...`. Click on one of them
5. Scroll down the **Headers** section until you find the required Headers, as in the `auth.txt`
6. Copy the headers exactly as they are; note that for the cookie key, you only need the part starting with `__Secure-next-auth.session-token=...`
7. Paste values into `auth.txt`

The interactive setup saves `auth.txt` with permissions `600` (owner read/write only) to protect your credentials. Never commit this file and store it securely.

---

## 🧩 `tagging_config.json` — OpenAI Tagging Setup

This file supplies the OpenAI API key and options used when generating tags for
images. It is created automatically on first run of the tagging command, or you
can create it manually with contents like:

```
{
  "api_key": "sk-...",
  "model": "gpt-4.1-mini",
  "prompt": "Generate concise, comma-separated tags describing this image.",
  "rename_prompt": "Create a short, descriptive filename slug (kebab-case) for this image."
}
```

Only `api_key` is required; `model` and `prompt` have sensible defaults. Keep
this file private—never commit it to version control.

### Non-interactive configuration

For scripted environments you can skip the interactive prompts by supplying
configuration through environment variables:

- Set `OPENAI_API_KEY`, `CHATGPT_LIBRARY_ARCHIVER_API_KEY`, or
  `CHATGPT_LIBRARY_ARCHIVER_OPENAI_API_KEY` to inject the API key at runtime.
- Optional overrides include `CHATGPT_LIBRARY_ARCHIVER_OPENAI_MODEL`,
  `CHATGPT_LIBRARY_ARCHIVER_TAG_PROMPT`, and
  `CHATGPT_LIBRARY_ARCHIVER_RENAME_PROMPT`.
- Combine these with `--no-config-prompt` to fail fast instead of asking to
  create `tagging_config.json`.

When these values are provided the tool caches OpenAI clients per API key and
uses them for tagging and renaming without mutating local configuration files.

---

## 🚀 3. Script Usage
### 🧭 Full Flow (Recommended):

1. **Run with venv bootstrap (recommended)**

```bash
python -m chatgpt_library_archiver bootstrap [--tag-new]
```
- Creates `.venv`, installs dependencies, and runs the full flow
- Use `--tag-new` to tag newly downloaded images after syncing

All high-level commands display a unified progress bar at the bottom of the
terminal while streaming status messages (including thumbnail generation) above
it so you can monitor each stage of the workflow without losing context.

2. **Run manually inside venv**

```bash
python -m chatgpt_library_archiver [--tag-new]
```
- Downloads **only new images**, adds them to `gallery/images`, updates `gallery/metadata.json`, creates `gallery/thumbs/<size>/<file>` thumbnails, and regenerates `gallery/index.html`
- Add `--tag-new` to tag fresh images during the download

3. **Regenerate gallery or thumbnails without downloading**

 ```bash
 python -m chatgpt_library_archiver gallery [--gallery DIR] [--regenerate-thumbnails] [--force-thumbnails]
 ```
 - Rebuilds the HTML gallery from existing files (sorts metadata and copies the
  bundled `index.html`).
 - Add `--regenerate-thumbnails` to (re)create entries in `gallery/thumbs/<size>/` for every
  image; combine with `--force-thumbnails` to overwrite existing thumbnails.

4. **Generate or manage image tags**

```bash
python -m chatgpt_library_archiver tag [--gallery DIR] [--all|--ids <id...>|--remove-all|--remove-ids <id...>] [--workers N]
```
- Populates the `tags` field in `metadata.json` using the OpenAI API. By
  default, only images missing tags are processed. Override the gallery location
  with `--gallery`. Use `--all` to re-tag every image, `--ids` to tag specific
  images, `--remove-all` to clear tags from all images, or `--remove-ids` to
  clear tags for specific images. The prompt and model can be overridden with
  `--prompt` and `--model`. The command reports progress as each image is
  tagged and displays per-image and total token usage when the API includes a
  `usage.total_tokens` field. It can run in parallel with `--workers`.

5. **Import local images into your gallery**

```bash
python -m chatgpt_library_archiver import <files_or_directories...> [options]
```

- Move local files into `gallery/images` and append metadata records.
- Provide `--copy` to copy instead of move (default is move).
- Use `--recursive` when passing directories to automatically traverse and import nested images.
- Apply one or more tags to all imported items with repeated `--tag` flags.
- Supply `--conversation-link` to attach a ChatGPT conversation URL for each file listed explicitly on the command line (directory imports skip this as they may expand to many files).
- Pass `--tag-new` to immediately tag imports using the existing OpenAI tagging workflow (honors `--tag-model`, `--tag-prompt`, and `--tag-workers`).
- Enable `--ai-rename` to request a descriptive filename from OpenAI. The `tagging_config.json` file supplies the API key and optionally a `rename_prompt` value for this feature. Provide `--rename-model` or `--rename-prompt` to override the defaults ad hoc.
- The tagging and renaming helpers now emit per-image telemetry that includes
  the tokens consumed, retry attempts due to rate limiting, and request
  latency—ideal for piping into structured logs during automated runs.
- Set a shared `--title` for all imported files or allow the tool to derive one from the filename/AI slug.
- Thumbnails are generated automatically in the `gallery/thumbs/<size>/` directories. Run the command with
  `--regenerate-thumbnails [--force-thumbnails]` to refresh thumbnails for existing
  entries without importing new files.

Use the `-y/--yes` flag with any command to bypass confirmation prompts.

---

## 🧱 Architecture Overview

The package is organized around a small set of composable modules so that
downloading, importing, tagging, and gallery generation can evolve
independently while sharing common infrastructure.

### Core modules and responsibilities

- `chatgpt_library_archiver/__main__.py` – entry point that mirrors running the
  package as a module (`python -m chatgpt_library_archiver`). It wires the CLI
  defaults to the incremental downloader.
- `chatgpt_library_archiver/cli/` – argument parsing and sub-command routing.
  `cli.app` owns the top-level parser while `cli.commands.*` modules wrap the
  individual workflows (`bootstrap`, `download`, `gallery`, `import`, `tag`).
- `chatgpt_library_archiver/incremental_downloader.py` – coordinates the
  network fetch loop, incremental metadata reconciliation, thumbnail creation,
  and optional tagging when downloading from ChatGPT.
- `chatgpt_library_archiver/importer.py` – ingests local files, normalises
  filenames, and appends metadata entries so local assets behave the same as
  remote downloads.
- `chatgpt_library_archiver/tagger.py` and `ai.py` – talk to the OpenAI APIs to
  generate tags or AI-assisted filenames. They centralise retry logic and rate
  limit handling so command modules can stay declarative.
- `chatgpt_library_archiver/gallery.py` and `gallery_index.html` – assemble the
  static gallery by sorting metadata, copying the bundled HTML shell, and
  emitting the JSON payload consumed by the browser UI.
- `chatgpt_library_archiver/thumbnails.py` – resizes images into the
  `thumbs/<size>/` directories and tracks where thumbnails land so metadata can
  reference them.
- `chatgpt_library_archiver/http_client.py` – wraps `httpx` with checksums,
  strict content-type validation, and streaming support that the downloader and
  importer reuse.
- `chatgpt_library_archiver/metadata.py` – defines the `GalleryItem` data class,
  JSON serialisation helpers, and timestamp normalisation utilities.
- `chatgpt_library_archiver/status.py` – a small status reporter used to surface
  progress bars, log lines, and aggregated error summaries across commands.
- `chatgpt_library_archiver/bootstrap.py` and `utils.py` – create virtual
  environments, install dependencies, and manage user prompts and config file
  discovery (`auth.txt`, `tagging_config.json`).

Each command-specific module constructs the dependencies it needs (e.g. the HTTP
client or status reporter) and delegates to these shared building blocks.

### Gallery data layout

The gallery directory remains intentionally flat so static hosting and manual
inspection stay straightforward:

```
gallery/
├── images/                # Original assets, named by their ChatGPT ID
├── thumbs/{small,medium,large}/
├── metadata.json          # Array of GalleryItem records
└── index.html             # Copied from gallery_index.html template
```

`metadata.json` is the single source of truth for the gallery. Each object in
the array mirrors `GalleryItem` and may include:

- `id` – stable identifier from the ChatGPT API or importer.
- `filename` – basename located under `gallery/images/`.
- `title`, `prompt` – human-readable metadata sourced from ChatGPT or CLI
  prompts.
- `created_at` – Unix timestamp (float) used for chronological sorting.
- `width`, `height` – recorded image dimensions when known.
- `url` – original CDN location for reproducibility (optional).
- `conversation_id`, `message_id`, `conversation_link` – traceability back to
  the originating ChatGPT conversation.
- `tags` – list of strings generated via the tagger workflow.
- `thumbnail` – default thumbnail path (usually `thumbs/medium/<file>`).
- `thumbnails` – mapping of size -> relative path under `gallery/thumbs/`.
- `checksum`, `content_type` – SHA-256 hash and MIME type captured during
  download/import.
- `extra` – JSON object that preserves unknown keys for forward compatibility.

Avoid editing `metadata.json` manually—use the CLI workflows so helper fields
such as `thumbnails` and `checksum` stay in sync.

## 💡 Notes

- No old data is overwritten. All images are saved with unique filenames and metadata is appended.
- The gallery is fully static and self-contained.
- The `index.html` viewer is bundled with the tool and reused on each run.
- `gallery/index.html` loads `metadata.json` via JavaScript and displays all images on one page.
- Images are lazy-loaded using the Intersection Observer API so they're fetched only when they enter the viewport.
- Downloads use a resilient HTTP client with retry/backoff, stream images directly to disk, store SHA-256 checksums and content types in `metadata.json`, and surface actionable error summaries via the progress reporter.
- A sticky header keeps the page title, search filters, and settings visible while you browse.
- The header and image grid span the full width of the viewport, and thumbnails are centered within their square cells.
- Switch to the **Full size** layout to show each image edge-to-edge using its full-resolution asset—perfect for mobile browsing.
- Use the header's search filters to filter by title or tags with fuzzy matching
  and Boolean expressions (AND/OR/NOT) or by a date range.
- Hover over a thumbnail to reveal its title, timestamp, tags, and conversation link;
  the grid hides these details by default to keep the focus on the images. Small
  thumbnails omit the timestamp and tags to keep overlays compact.
- The gallery respects your system's light or dark preference, and the **Toggle Dark Mode** button lets you override it.
- Your selected theme, image size, and filter values are remembered for the current browser session.
- Click any thumbnail to open a full-screen viewer overlay. Navigate with the left/right
  arrow keys, press Escape to close, or follow the **Raw file** link to view the
  underlying image. Tap or click anywhere to dismiss the overlay, or swipe left/right on touch devices to jump between images.
  Ctrl-click (Cmd-click on macOS) a thumbnail to open the raw image directly in a new
  tab without launching the viewer.

### Disk Space
This depends entirely on how many images you have.
General estimate:
- 1 image ≈ 1.8–3.3 MB
- 100 images ≈ 180–330 MB
- 1,000 images ≈ 2–3 GB
- 5,000 images ≈ 10–12 GB

---

## ❓ Troubleshooting

- If you get a `403` or `401`, your token or cookie may have expired. Refresh `auth.txt` by copying headers again from your browser.
- During downloads, if a `401/403` occurs, the downloader now offers to re-enter credentials interactively.
- If no new images are found, the downloader simply exits without changes.

---

## 🧪 Testing and Linting

The project leans on pytest, Ruff, and Pyright. `make lint` and `make test`
mirror the CI pipeline and enforce formatting, static typing, and a minimum of
85% coverage.

### Test suite layout

- `tests/test_cli.py` – verifies argument parsing and sub-command wiring.
- `tests/test_end_to_end.py` – exercises the download pipeline, metadata
  reconciliation, tagging, and gallery regeneration in a hermetic filesystem.
- `tests/test_gallery.py`, `tests/test_thumbnails.py`, `tests/test_metadata.py`
  – cover pure rendering and data transformation helpers.
- `tests/test_http_client.py`, `tests/test_status.py`, `tests/test_utils.py` –
  focus on infrastructure primitives and error handling.
- `tests/test_importer.py`, `tests/test_tagger.py`, `tests/test_ai.py` – validate
  import flows and OpenAI integration points by stubbing HTTP calls.
- `tests/test_bootstrap.py`, `tests/test_pre_commit_hook.py` – guard the
  development tooling.

The tests favour dependency injection and monkeypatching so new behaviour can be
covered without performing real network requests or writing outside the
temporary directory created by pytest fixtures.

### Running and extending tests

```
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
pre-commit run --all-files
make lint
make test
```

When adding a feature, mirror the existing module-level test files so new cases
live alongside the behaviour they exercise. Prefer constructing fake HTTP
clients and in-memory images (see `tests/test_end_to_end.py`) over touching real
network resources. If a workflow depends on filesystem state, target the
`tmp_path` fixture so the suite stays deterministic. Add focused unit tests for
helpers, then augment the end-to-end flow if the user journey changes. Finally,
run `make lint` and `make test` locally before pushing to confirm the coverage
gate and static analysis still pass.

### Git hook

To ensure linting and tests pass before commits are created, configure Git to
use the provided hooks:

```
git config core.hooksPath .githooks
```

The pre-commit hook runs `make lint` and `make test` and will block the commit
if either step fails.

To build a distributable package:

```
python -m build
```

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request. Before committing, run `pre-commit run --all-files` and `pytest` to ensure tests and linters pass.

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

## ✅ You're All Set

Once configured, rerun `python -m chatgpt_library_archiver` any time you generate new images in ChatGPT.

Happy archiving!
