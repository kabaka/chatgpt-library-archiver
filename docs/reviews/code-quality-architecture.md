# Code Quality & Architecture Review

**Project**: chatgpt-library-archiver
**Date**: 2026-03-01
**Scope**: All source files under `src/chatgpt_library_archiver/` and `src/chatgpt_library_archiver/cli/`
**Total source lines**: ~3,589

---

## 1. Module Organization

**Rating: Good**

The project has a sensible top-level structure with clear separation of concerns:

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `metadata.py` | 209 | Data models and JSON persistence |
| `http_client.py` | 299 | HTTP transport with retries and streaming |
| `ai.py` | 178 | OpenAI client helpers and telemetry |
| `thumbnails.py` | 335 | Image thumbnail generation (Pillow) |
| `incremental_downloader.py` | 287 | API pagination + concurrent downloads |
| `importer.py` | 438 | Local image import pipeline |
| `tagger.py` | 261 | OpenAI-based image tagging |
| `browser_extract.py` | 508 | macOS cookie decryption for auth |
| `gallery.py` | 49 | Gallery HTML generation |
| `status.py` | 144 | Progress bar / status reporting |
| `utils.py` | 109 | Shared utilities (auth, prompts) |
| `bootstrap.py` | 139 | Environment setup |
| `cli/` | ~571 | CLI parsing and command dispatch |

**Strengths**:
- Most modules stay under or near 300 lines. Only `browser_extract.py` (508) and `importer.py` (438) are larger, and both have genuine complex domain logic that justifies the size.
- The CLI layer is cleanly separated into `cli/app.py` (wiring) and `cli/commands/` (one file per subcommand).
- No circular dependencies at the top level. The two deferred imports in [incremental_downloader.py](src/chatgpt_library_archiver/incremental_downloader.py#L50) and [browser_extract.py](src/chatgpt_library_archiver/browser_extract.py#L342) are correctly scoped inside functions to avoid circular import chains and to keep `browser_extract` optional on non-macOS platforms.

**Issues**:
- **`importer.py` is a borderline god module.** It handles file collection, AI renaming, file copy/move, thumbnail creation, metadata updates, tagging orchestration, argparse definition, and gallery regeneration — all in one file. The `import_images()` function alone at [importer.py L151–291](src/chatgpt_library_archiver/importer.py#L151-L291) spans ~140 lines and has 16 parameters.
- **Duplicate `parse_args()` definitions.** Both [importer.py L297](src/chatgpt_library_archiver/importer.py#L297) and [tagger.py L211](src/chatgpt_library_archiver/tagger.py#L211) define standalone `parse_args()` functions with near-identical argument sets that overlap heavily with the CLI commands in `cli/commands/`. These appear to be legacy remnants from before the CLI refactor.

**Recommendations**:
1. Extract the file-collection and AI-rename logic from `importer.py` into smaller focused functions or a helper module.
2. Remove the standalone `parse_args()` / `main()` in `importer.py` and `tagger.py` if they're only used via the CLI layer. If they serve as standalone entry points, document that clearly.

---

## 2. Type Safety

**Rating: Adequate**

**Strengths**:
- Modern union syntax (`str | None`) used consistently via `from __future__ import annotations`.
- `GalleryItem` dataclass in [metadata.py](src/chatgpt_library_archiver/metadata.py#L79-L98) is well-typed with proper field factories.
- The `from_dict()` constructor in [metadata.py L101–160](src/chatgpt_library_archiver/metadata.py#L101-L160) carefully coerces and validates each field rather than using `**kwargs`.
- `HttpError` in [http_client.py L18–50](src/chatgpt_library_archiver/http_client.py#L18-L50) has structured, typed fields.

**Issues**:
- **Pyright strict mode is scoped to only `metadata.py`** ([pyproject.toml L100–103](pyproject.toml#L100-L103)):
  ```toml
  [tool.pyright]
  typeCheckingMode = "strict"
  include = ["src/chatgpt_library_archiver/metadata.py"]
  ```
  This means the rest of the codebase gets no static type checking enforcement.

- **Seven functions return bare `dict`** without generic parameters, losing all type information at call sites:
  ```python
  # tagger.py L29, L34, L53
  def _load_config(path: str) -> dict:
  def _write_config(path: str) -> dict:
  def ensure_tagging_config(...) -> dict:

  # utils.py L50, L67, L91
  def load_auth_config(path: str = "auth.txt") -> dict:
  def prompt_and_write_auth(path: str = "auth.txt") -> dict:
  def ensure_auth_config(path: str = "auth.txt") -> dict:

  # incremental_downloader.py L28
  def build_headers(config: dict) -> dict:
  ```

- **`Any` usage in `ai.py`** is pragmatic but could be tighter. The `resolve_config()` function at [ai.py L58–100](src/chatgpt_library_archiver/ai.py#L58-L100) takes and returns `dict[str, Any]`, which erases all type safety for config values. The `_extract_usage(usage: Any | None)` at [ai.py L112](src/chatgpt_library_archiver/ai.py#L112) relies on `getattr` duck-typing against the OpenAI response object.

- **Four files missing `from __future__ import annotations`**:
  - [\_\_init\_\_.py](src/chatgpt_library_archiver/__init__.py)
  - [cli/\_\_init\_\_.py](src/chatgpt_library_archiver/cli/__init__.py)
  - [utils.py](src/chatgpt_library_archiver/utils.py)
  - [gallery.py](src/chatgpt_library_archiver/gallery.py)

**Recommendations**:
1. Expand pyright strict mode incrementally. Prioritize `ai.py`, `http_client.py`, and `status.py` next — they have the cleanest signatures already.
2. Create a `TaggingConfig` dataclass (or at minimum a `TypedDict`) to replace the raw `dict` return types in `tagger.py` and `ai.py`.
3. Create an `AuthConfig` TypedDict for `utils.py`'s auth functions.
4. Add `from __future__ import annotations` to the four missing files.

---

## 3. Error Handling Patterns

**Rating: Good**

**Strengths**:
- `HttpError` in [http_client.py](src/chatgpt_library_archiver/http_client.py#L18-L50) is a best-practice structured exception with URL, status code, reason, details, and the original response — excellent for debugging.
- `browser_extract.py` defines a clear exception hierarchy:
  ```
  BrowserExtractError (RuntimeError)
  ├── PlatformNotSupportedError (NotImplementedError)
  ├── BrowserNotFoundError
  ├── KeychainAccessError
  ├── CookieDecryptionError
  ├── SessionExpiredError
  └── TokenFetchError
  ```
  These are defined at [browser_extract.py L91–117](src/chatgpt_library_archiver/browser_extract.py#L91-L117) and give callers precise control over error handling.
- `StatusReporter.report_error()` at [status.py L101–115](src/chatgpt_library_archiver/status.py#L101-L115) captures structured error data (`StatusError` dataclass) rather than just printing strings.
- No bare `except:` clauses anywhere in the codebase.

**Issues**:
- **Swallowed exceptions in `importer.py`** at [line 246](src/chatgpt_library_archiver/importer.py#L246):
  ```python
  except Exception:
      slug = None
  ```
  AI rename failures are silently discarded. While the fallback to the filename stem is reasonable, the exception should at least be logged to the reporter.

- **Silent `except Exception` in `browser_extract.py`** at [line 433](src/chatgpt_library_archiver/browser_extract.py#L433):
  ```python
  except Exception:
      return ""
  ```
  `_scrape_client_version()` silently returns empty string on any failure. Network errors, parsing errors, and programming bugs all get the same treatment.

- **Broad `except Exception` as safety nets** at [incremental_downloader.py L117](src/chatgpt_library_archiver/incremental_downloader.py#L117) and [L148](src/chatgpt_library_archiver/incremental_downloader.py#L148) — these are marked with `# pragma: no cover - safety net`, indicating they're acknowledged but never tested.

- **Missing error context in `thumbnails.py`** at [line 181](src/chatgpt_library_archiver/thumbnails.py#L181):
  ```python
  except (FileNotFoundError, UnidentifiedImageError, OSError) as exc:
      raise RuntimeError(f"Failed to create thumbnail for {source}: {exc}") from exc
  ```
  Wrapping into generic `RuntimeError` loses the specific exception type that callers might want to handle differently.

**Recommendations**:
1. Log swallowed AI rename exceptions to the `StatusReporter` in `importer.py`.
2. Create a `ThumbnailError` exception class rather than wrapping into generic `RuntimeError`.
3. Add at minimum debug-level logging to the `_scrape_client_version` catch-all.

---

## 4. Function Complexity

**Rating: Needs Improvement**

The ruff per-file ignores in [pyproject.toml L77–87](pyproject.toml#L77-L87) explicitly acknowledge complexity problems:

```toml
"src/chatgpt_library_archiver/importer.py" = ["PLR0912", "PLR0913", "PLR0915"]
"src/chatgpt_library_archiver/incremental_downloader.py" = ["PLC0415", "PLR0912", "PLR0915"]
"src/chatgpt_library_archiver/tagger.py" = ["PLR0912", "PLR0913", "PLR0915"]
"src/chatgpt_library_archiver/thumbnails.py" = ["PLR0912", "PLR0915"]
"src/chatgpt_library_archiver/browser_extract.py" = ["PLC0415", "PLR0913", "S603", "S607", "SLF001"]
```

This means **5 out of 12 core modules** have suppressed complexity warnings.

**Specific hotspots**:

| Function | Location | Issue |
|----------|----------|-------|
| `import_images()` | [importer.py L151](src/chatgpt_library_archiver/importer.py#L151) | 16 parameters (PLR0913), ~140 lines (PLR0915), 12+ branches (PLR0912) |
| `main()` in downloader | [incremental_downloader.py L47](src/chatgpt_library_archiver/incremental_downloader.py#L47) | ~240 lines, deeply nested while/for/if/try blocks, inline `download_image()` closure |
| `tag_images()` | [tagger.py L112](src/chatgpt_library_archiver/tagger.py#L112) | 11 parameters, 4 levels of nesting |
| `regenerate_thumbnails()` | [thumbnails.py L211](src/chatgpt_library_archiver/thumbnails.py#L211) | Complex multiprocessing setup with status queue plumbing |

**Decomposition strategies**:

1. **`incremental_downloader.main()`**: Extract the API pagination loop into `_fetch_all_new_items(client, headers, existing_ids, progress) -> list[GalleryItem]` and the download-with-retry logic into a named top-level function instead of the nested `download_image()` closure.

2. **`import_images()`**: Group the 16 parameters into configuration dataclasses:
   ```python
   @dataclass
   class ImportConfig:
       gallery_root: str = "gallery"
       copy_files: bool = False
       recursive: bool = False
       tags: list[str] = field(default_factory=list)
       title: str | None = None
       # ...
   ```

3. **`tag_images()`**: Split the remove-tags path and the generate-tags path into separate functions; the current function does both, controlled by boolean flags.

---

## 5. Code Duplication

**Rating: Adequate**

**Identified duplications**:

1. **User-Agent string** hardcoded in three places:
   - [browser_extract.py L353](src/chatgpt_library_archiver/browser_extract.py#L353) (in `fetch_access_token`)
   - [browser_extract.py L420](src/chatgpt_library_archiver/browser_extract.py#L420) (in `_scrape_client_version`)
   - [browser_extract.py L474](src/chatgpt_library_archiver/browser_extract.py#L474) (in `extract_auth_config`)

   Should be extracted to a module-level `_DEFAULT_USER_AGENT` constant.

2. **`HttpClient(timeout=30.0)` instantiation** appears three times:
   - [browser_extract.py L342](src/chatgpt_library_archiver/browser_extract.py#L342)
   - [browser_extract.py L413](src/chatgpt_library_archiver/browser_extract.py#L413)
   - [incremental_downloader.py L44](src/chatgpt_library_archiver/incremental_downloader.py#L44) (`create_http_client()` factory)

   `browser_extract.py` should use the same factory or accept an `HttpClient` via dependency injection.

3. **Duplicate CLI argument definitions**: The `parse_args()` functions in [importer.py L297–367](src/chatgpt_library_archiver/importer.py#L297-L367) and [tagger.py L211–231](src/chatgpt_library_archiver/tagger.py#L211-L231) duplicate arguments already defined in [cli/commands/import_command.py](src/chatgpt_library_archiver/cli/commands/import_command.py) and [cli/commands/tag.py](src/chatgpt_library_archiver/cli/commands/tag.py).

4. **`DEFAULT_RENAME_PROMPT`** is defined in [importer.py L36](src/chatgpt_library_archiver/importer.py#L36) while `DEFAULT_PROMPT` for tagging is in [tagger.py L24](src/chatgpt_library_archiver/tagger.py#L24). Both prompt defaults should live in a central config or constants module.

5. **Thumbnail path computation** — `thumbnail_relative_paths()` is called, then each path is resolved against `gallery_root`, in both [importer.py L268–269](src/chatgpt_library_archiver/importer.py#L268-L269) and [incremental_downloader.py L99–102](src/chatgpt_library_archiver/incremental_downloader.py#L99-L102). A helper like `thumbnail_absolute_paths(gallery_root, filename)` would reduce this two-step pattern.

**Recommendations**:
1. Extract `_DEFAULT_USER_AGENT` to a shared constant.
2. Consolidate `HttpClient` creation in `browser_extract.py`.
3. Remove duplicate `parse_args()`/`main()` functions from `importer.py` and `tagger.py` or clearly document them as standalone entry points.

---

## 6. Configuration Management

**Rating: Adequate**

Two distinct configuration systems exist:

1. **Auth config** (`auth.txt`): Key-value flat file parsed in [utils.py L50–64](src/chatgpt_library_archiver/utils.py#L50-L64). Required keys are validated against `REQUIRED_AUTH_KEYS` at [utils.py L3–11](src/chatgpt_library_archiver/utils.py#L3-L11).

2. **Tagging config** (`tagging_config.json`): JSON file loaded in [tagger.py L29–33](src/chatgpt_library_archiver/tagger.py#L29-L33), merged with environment variables and overrides in [ai.py L58–100](src/chatgpt_library_archiver/ai.py#L58-L100).

**Strengths**:
- Environment variable override chain in `ai.py` (`resolve_config`) supports three env var names for the API key, correctly prioritizing project-specific names over generic `OPENAI_API_KEY`.
- Auth file creation uses `os.open()` with mode `0o600` at [utils.py L85](src/chatgpt_library_archiver/utils.py#L85) — good security practice.
- Explicit rejection of API key overrides via function parameters at [ai.py L66–68](src/chatgpt_library_archiver/ai.py#L66-L68).

**Issues**:
- **No config validation beyond key existence.** The auth config just checks that keys are present, not that values are plausible (e.g., `authorization` starts with "Bearer ", `url` is a valid URL).
- **Config types are raw `dict`** everywhere — no `TypedDict`, dataclass, or Pydantic model. Config values are accessed with string-key dict lookups, which are a source of typo bugs.
- **Scattered config defaults**: `"gpt-4.1-mini"` appears as a default in [ai.py L16](src/chatgpt_library_archiver/ai.py#L16), [tagger.py L35](src/chatgpt_library_archiver/tagger.py#L35), [tagger.py L161](src/chatgpt_library_archiver/tagger.py#L161), and [importer.py L109](src/chatgpt_library_archiver/importer.py#L109). It should be defined once and imported.

**Recommendations**:
1. Create typed config models (`TaggingConfig`, `AuthConfig`) as dataclasses or TypedDicts.
2. Centralize `DEFAULT_MODEL` from `ai.py` and remove duplicated literal strings.
3. Add semantic validation for auth config values.

---

## 7. CLI Architecture

**Rating: Excellent**

**Strengths**:
- Clean command pattern: each subcommand is a `@dataclass` with `register()` and `handle()` methods in `cli/commands/`.
- Dependency injection via `create_app()` in [cli/app.py L70–115](src/chatgpt_library_archiver/cli/app.py#L70-L115) wires production dependencies while making the CLI fully testable.
- The `CLI` dataclass at [cli/app.py L17–37](src/chatgpt_library_archiver/cli/app.py#L17-L37) is minimal: just `parser` + `default_handler` with `parse_args()` and `run()`.
- `__main__.py` at [\_\_main\_\_.py L13–24](src/chatgpt_library_archiver/__main__.py#L13-L24) builds the app with `build_app()` then delegates, keeping wiring separate from execution.
- Global `--yes` flag properly sets `ARCHIVER_ASSUME_YES` env var at [\_\_main\_\_.py L38](src/chatgpt_library_archiver/__main__.py#L38), which `prompt_yes_no()` respects.

**Minor issues**:
- `ImportCommand.handle()` at [import_command.py L105–160](src/chatgpt_library_archiver/cli/commands/import_command.py#L105-L160) uses excessive `getattr(args, ...)` calls where direct attribute access would be safe (since `register()` sets defaults for all attributes). This is defensive but adds noise.
- The `GalleryCommand.handle()` at [gallery.py L41–55](src/chatgpt_library_archiver/cli/commands/gallery.py#L41-L55) calls the runner with `gallery_root=gallery_root` keyword but `generate_gallery()` expects a positional argument, which works but is fragile.

---

## 8. Data Flow

**Rating: Good**

The main pipeline flows as:

```
API → incremental_downloader.main()
        → HttpClient.get_json()          [metadata pages]
        → HttpClient.stream_download()   [image bytes]
        → thumbnails.create_thumbnails() [Pillow resize]
        → save_gallery_items()           [metadata.json]
        → tagger.tag_images()            [optional AI tags]
        → gallery.generate_gallery()     [HTML output]
```

**Strengths**:
- Streaming downloads with SHA-256 checksums via [http_client.py L202–272](src/chatgpt_library_archiver/http_client.py#L202-L272) prevent memory bloat and enable integrity checks.
- Content-type validation before image processing.
- Atomic-ish download pattern: write to `.download` temp file, then `replace()` at [incremental_downloader.py L95–96](src/chatgpt_library_archiver/incremental_downloader.py#L95-L96).
- Gallery items use an `extra` dict at [metadata.py L98](src/chatgpt_library_archiver/metadata.py#L98) to round-trip unknown fields from JSON, ensuring forward/backward compatibility.

**Issues**:
- **Metadata saved only after all downloads complete** in `incremental_downloader.main()`. If the process crashes mid-batch, all progress for that page is lost. The `save_gallery_items()` call at [incremental_downloader.py L240](src/chatgpt_library_archiver/incremental_downloader.py#L240) is outside the pagination loop.
- **Thumbnail regeneration called twice during import** — once per-file in the import loop at [importer.py L268–271](src/chatgpt_library_archiver/importer.py#L268-L271), and again for the full gallery at [importer.py L286](src/chatgpt_library_archiver/importer.py#L286). The second call to `thumbnails.regenerate_thumbnails()` will largely be a no-op due to the existence check, but it still scans every file.
- **Gallery generation is always called** at the end of `incremental_downloader.main()` at [line 254](src/chatgpt_library_archiver/incremental_downloader.py#L254), even when no new images were downloaded.

**Recommendations**:
1. Save metadata incrementally after each page of downloads completes, not just at the end.
2. Skip the full `regenerate_thumbnails()` call in `importer.py` when thumbnails were already created in-loop.
3. Gate `generate_gallery()` behind `if new_metadata:` in the downloader.

---

## 9. Concurrency Model

**Rating: Good**

**Strengths**:
- **Thread-safe HTTP sessions**: `HttpClient` uses `threading.local()` for per-thread sessions and a `threading.Lock` for the session registry at [http_client.py L97–115](src/chatgpt_library_archiver/http_client.py#L97-L115).
- **`ThreadPoolExecutor` for I/O-bound downloads** at [incremental_downloader.py L174](src/chatgpt_library_archiver/incremental_downloader.py#L174) with 14 workers — appropriate for network-bound work.
- **`ProcessPoolExecutor` for CPU-bound thumbnails** at [thumbnails.py L260](src/chatgpt_library_archiver/thumbnails.py#L260) — correct choice since Pillow operations release the GIL for some but not all operations.
- **Bounded submission pattern** in `regenerate_thumbnails()`: new work is submitted only when a previous future completes at [thumbnails.py L316–327](src/chatgpt_library_archiver/thumbnails.py#L316-L327), preventing unbounded queue growth.
- **Cross-process status reporting** via a `multiprocessing.Manager().Queue()` with a dedicated consumer thread at [thumbnails.py L270–280](src/chatgpt_library_archiver/thumbnails.py#L270-L280) — well-designed pattern.

**Issues**:
- **Potential race condition in tagger**: `tag_images()` at [tagger.py L160–182](src/chatgpt_library_archiver/tagger.py#L160-L182) uses `ThreadPoolExecutor` to process items concurrently. The `process()` closure mutates `item.tags` directly. While each `item` is unique, the `total_tokens` and `total_latency` accumulators at [tagger.py L156–157](src/chatgpt_library_archiver/tagger.py#L156-L157) are shared across the main thread that calls `as_completed()` — this is safe because `as_completed()` serializes the result processing, but it's fragile. If the accumulation logic were moved into the `process()` callback, it would become a real race condition.
- **`download_image()` closure in `incremental_downloader.py`** at [line 81](src/chatgpt_library_archiver/incremental_downloader.py#L81) mutates `item.filename`, `item.checksum`, etc. on the `GalleryItem` objects. Since each item is distinct, this is safe, but the mutation-from-thread pattern makes it hard to reason about.
- **No concurrency for the download phase in `importer.py`** — files are imported sequentially in a single-threaded loop at [importer.py L220–285](src/chatgpt_library_archiver/importer.py#L220-L285), even when processing many files.

**Recommendations**:
1. Have `download_image()` return a new `GalleryItem` (or a result DTO) instead of mutating the input item.
2. Consider adding concurrent processing to `import_images()` for large batch imports.

---

## 10. Python Best Practices

**Rating: Good**

**Strengths**:
- `pathlib.Path` used extensively in `http_client.py`, `metadata.py`, `thumbnails.py`, `importer.py`, and `browser_extract.py`.
- `dataclass(slots=True)` used for core models: `GalleryItem`, `AIRequestTelemetry`, `DownloadResult`, `HttpError`, `BrowserProfile`, `StatusError`.
- Context managers used for `HttpClient` (`__enter__`/`__exit__`) at [http_client.py L119–123](src/chatgpt_library_archiver/http_client.py#L119-L123), `StatusReporter` (inherits `AbstractContextManager`) at [status.py L54](src/chatgpt_library_archiver/status.py#L54).
- `field(default_factory=...)` instead of mutable defaults in dataclasses.
- Proper `from __future__ import annotations` in most modules (with 4 exceptions noted in §2).
- f-strings used consistently; no `%` formatting or `.format()` calls.

**Issues**:
- **`bootstrap.py` uses `os.path` exclusively** — [12 occurrences](src/chatgpt_library_archiver/bootstrap.py) while the rest of the project uses `pathlib`. This is the only module with zero `pathlib` usage.
- **`gallery.py` uses `os.path.join`** at [line 38](src/chatgpt_library_archiver/gallery.py#L38) alongside `importlib.resources` — mixing old and new patterns.
- **`tagger.py` uses `os.path.join`** at [line 165](src/chatgpt_library_archiver/tagger.py#L165) in a single spot amid `Path` usage elsewhere.
- **`open()` in `metadata.py`** at [lines 195 and 203](src/chatgpt_library_archiver/metadata.py#L195) uses `open(path)` instead of `path.open()`, despite `path` being a `Path` object.
- **`bootstrap.main()` missing return type** at [line 120](src/chatgpt_library_archiver/bootstrap.py#L120): `def main(tag_new: bool = False):` — no return annotation.

**Recommendations**:
1. Migrate `bootstrap.py` to `pathlib`.
2. Use `path.open()` instead of `open(path)` for consistency when the path is already a `Path`.
3. Add return type annotations to `bootstrap.main()`.

---

## 11. API Design (Internal)

**Rating: Good**

**Strengths**:
- **Dependency injection is the norm**: `create_app()` injects all runners, `call_image_endpoint()` takes a `client` parameter, `create_thumbnails()` takes a `reporter` parameter.
- **Return types are informative**: `stream_download()` returns `DownloadResult` with path, bytes, checksum, and content type. `call_image_endpoint()` returns a well-structured `(text, telemetry, usage)` tuple.
- **Callbacks over inheritance**: `on_retry` callback at [ai.py L131](src/chatgpt_library_archiver/ai.py#L131) lets callers customize retry reporting without subclassing.
- **`StatusReporter`** provides a clean interface: `log()`, `log_status()`, `report_error()`, `advance()`, `add_total()`.

**Issues**:
- **Inconsistent return types for "main" functions**:
  - `incremental_downloader.main()` returns `None` (void).
  - `tagger.main()` returns `int` (count of updated images).
  - `importer.main()` returns `int` (count of imports).
  - `bootstrap.main()` calls `sys.exit()` directly at [line 135](src/chatgpt_library_archiver/bootstrap.py#L135).

  The CLI already abstracts over these via `command_handler`, but the inconsistency makes it harder to compose functions in tests or new pipelines.

- **`tag_images()` conflates two operations** — it both generates and removes tags depending on boolean flags. A cleaner API would be `tag_images()` and `remove_tags()` as separate functions.

- **Mixed positional and keyword arguments**: `generate_gallery(gallery_root: str = "gallery")` at [gallery.py L16](src/chatgpt_library_archiver/gallery.py#L16) uses a positional parameter, while `tag_images()` at [tagger.py L112](src/chatgpt_library_archiver/tagger.py#L112) uses keyword-only parameters mixed with positional ones.

**Recommendations**:
1. Standardize all "runner" functions to return `int` exit codes.
2. Split `tag_images()` into `tag_images()` and `remove_tags()`.
3. Use keyword-only parameters (after `*`) for functions with more than 3 parameters.

---

## 12. Naming Conventions

**Rating: Good**

**Strengths**:
- Module names are descriptive and follow Python conventions: `incremental_downloader`, `http_client`, `browser_extract`, `metadata`.
- Private functions correctly prefixed with `_`: `_derive_key`, `_mask`, `_entry_get`, `_parse_created_at_string`.
- Constants are `UPPER_SNAKE_CASE`: `THUMBNAIL_SIZES`, `DEFAULT_MODEL`, `HTTP_ERROR_STATUS`.
- Dataclass names are clear nouns: `GalleryItem`, `DownloadResult`, `AIRequestTelemetry`, `BrowserProfile`, `EnvironmentInfo`.

**Minor issues**:
- **`_entry_get` / `_entry_set`** in [thumbnails.py L23–34](src/chatgpt_library_archiver/thumbnails.py#L23-L34) are generic names for what is essentially a `GalleryItem | dict` adapter. Consider naming them `_get_item_field` / `_set_item_field` or, better yet, requiring `GalleryItem` objects exclusively and removing the dict compatibility.
- **`import_command.py`** filename breaks the one-word-per-module convention used by other commands (`bootstrap.py`, `download.py`, `gallery.py`, `tag.py`). This is due to `import` being a Python reserved word, which is unavoidable.
- **`metas` variable** in [incremental_downloader.py L156](src/chatgpt_library_archiver/incremental_downloader.py#L156) is an unusual abbreviation that could be `new_gallery_items` for clarity.

---

## Summary

| Area | Rating | Priority |
|------|--------|----------|
| Module Organization | Good | Medium |
| Type Safety | Adequate | High |
| Error Handling Patterns | Good | Low |
| Function Complexity | Needs Improvement | High |
| Code Duplication | Adequate | Medium |
| Configuration Management | Adequate | Medium |
| CLI Architecture | Excellent | — |
| Data Flow | Good | Medium |
| Concurrency Model | Good | Low |
| Python Best Practices | Good | Low |
| API Design | Good | Medium |
| Naming Conventions | Good | Low |

### Top 5 Actionable Items

1. **Expand pyright strict mode** beyond `metadata.py`. Add `ai.py`, `http_client.py`, `status.py`, `gallery.py`, and `thumbnails.py` to the include list. These modules are already close to strict-compatible.

2. **Decompose `incremental_downloader.main()`** (~240 lines). Extract the pagination loop and the `download_image` closure into top-level functions. This eliminates the deepest nesting and the PLR0912/PLR0915 suppression.

3. **Introduce typed config models** (`TaggingConfig`, `AuthConfig`) to replace the 7 functions that return bare `dict`. This catches key-name typos at type-check time and makes signatures self-documenting.

4. **Refactor `import_images()`** — group its 16 parameters into one or two configuration dataclasses. Extract the AI-rename block and the per-file import-loop body into named functions.

5. **Save metadata incrementally** in the download loop. If the process dies mid-batch, all progress for that batch is currently lost. Saving after each API page would limit the blast radius.
