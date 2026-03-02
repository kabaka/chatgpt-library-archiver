# Implementation Plan — chatgpt-library-archiver

**Created:** 2026-03-01
**Status:** Active
**Purpose:** Coordination document for the orchestrator agent to drive all improvement work derived from the 9 consolidated review reports.

---

## How to Use This Document

**For the orchestrator (`@orchestrator-manager`):**
1. Identify the current batch (the first batch with status "Not Started" or "In Progress").
2. Assign work items to specialist agents by referencing the agent column.
3. When a batch is complete, update its status and move to the next batch.

**For specialist agents:**
1. Check which batch is current and find your assigned item(s).
2. Read the referenced review document(s) for detailed guidance, code examples, and rationale.
3. Implement the change, run `pre-commit run --all-files`, and confirm `make lint && make test` pass.
4. Update the Status field to "Done" when complete.

**Status values:** `Not Started` · `In Progress` · `Done` · `Blocked` · `Deferred`

---

## Batch Status Summary

| Batch | Theme | Items | Status | Dependencies |
|-------|-------|-------|--------|--------------|
| 1 | Critical Security & Correctness Fixes | 6 | Not Started | — |
| 2 | Security Hardening (HTTP, Images, Gallery) | 7 | Not Started | — |
| 3 | Test Infrastructure Foundations | 5 | Not Started | — |
| 4 | Batch Error Recovery & Resilience | 5 | Not Started | Batch 3 (ThumbnailError, conftest.py) |
| 5 | Documentation P0 — Accuracy & Onboarding | 6 | Not Started | — |
| 6 | Gallery Accessibility — Critical & High | 7 | Done | Batch 2 (XSS fix provides refactoring base) |
| 7 | API & HTTP Resilience Improvements | 7 | Done | — |
| 8 | Code Architecture & Type Safety | 6 | Not Started | — |
| 9 | CI/CD Pipeline Hardening | 7 | Done | — |
| 10 | Test Coverage Expansion | 7 | Done | Batch 3 (conftest.py), Batch 4 (error recovery) |
| 11 | Gallery UX — Navigation & Performance | 7 | Not Started | Batch 6 (accessibility base) |
| 12 | Function Decomposition & Data Flow | 5 | Done | Batch 8 (typed configs) |
| 13 | Image Pipeline & AI Cost Optimization | 6 | Not Started | Batch 4 (error recovery) |
| 14 | Pyright Expansion & Linting | 5 | Not Started | Batch 8 (typed configs) |
| 15 | Documentation & Skill File Updates | 8 | Not Started | Batch 5 (P0 docs), Batch 7 (API changes) |
| 16 | Gallery Visual Polish | 8 | Not Started | Batch 6 + 11 (gallery infrastructure) |
| 17 | Release Infrastructure & DevOps Polish | 7 | Not Started | Batch 9 (CI pipeline) |

---

## Batch 1 — Critical Security & Correctness Fixes

> These items address live credential exposure, data corruption risk, and a build-system correctness blocker. Fix before any other work.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 1.1 | Rotate exposed API key | The `tagging_config.json` in the working tree contains a real `sk-Zpp16...` API key. Rotate immediately at https://platform.openai.com/api-keys. Verify it was never committed: `git log --all --diff-filter=A -- tagging_config.json`. Replace value with `sk-YOUR-KEY-HERE`. | @security-auditor | [security-audit.md](security-audit.md) C-1, [openai-integration.md](openai-integration.md) §10 | — | Small | Not Started |
| 1.2 | Fix `tagging_config.json` file permissions | Change `_write_config()` in `tagger.py` to use `os.open()` with `0o600` mode instead of plain `open()`. Extract a shared `write_secure_file()` helper in `utils.py` that both `_write_config()` and auth writing can use. Also `chmod 600` the existing file. | @python-developer | [security-audit.md](security-audit.md) C-1, [openai-integration.md](openai-integration.md) §10 | — | Small | Not Started |
| 1.3 | Eliminate gallery XSS via innerHTML | Replace all `innerHTML` card construction in `gallery_index.html` with `document.createElement()` / `textContent` DOM API. Also add `safeHref()` URL scheme validation for `conversation_link` (block `javascript:`, `data:`, `vbscript:` schemes). This addresses stored XSS (H-1, SEC-1), href injection (SEC-2), and attribute breakout (SEC-3). | @gallery-ux-designer | [security-audit.md](security-audit.md) H-1, [gallery-ux-accessibility.md](gallery-ux-accessibility.md) SEC-1/2/3 & §12 | — | Medium | Not Started |
| 1.4 | Atomic metadata writes | Rewrite `save_gallery_items()` in `metadata.py` to write to a temp file then `os.replace()`. Use `tempfile.mkstemp()` in the same directory. This prevents `metadata.json` corruption on interrupted writes. | @python-developer | [security-audit.md](security-audit.md) H-4, [code-quality-architecture.md](code-quality-architecture.md) §8 | — | Small | Not Started |
| 1.5 | Suppress OpenAI SDK debug logging | Add `logging.getLogger("openai").setLevel(logging.WARNING)` at module scope in `ai.py` to prevent API key leakage through debug log output. | @openai-specialist | [security-audit.md](security-audit.md) M-5, [openai-integration.md](openai-integration.md) §1 | — | Small | Not Started |
| 1.6 | Fix ruff version mismatch | Update `.pre-commit-config.yaml` to use `language: system` hooks that delegate to the venv-installed ruff, eliminating the version mismatch between pre-commit (v0.5.7) and local/CI (v0.13.0) that causes `make lint` to fail while `pre-commit` passes. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §3 | — | Small | Not Started |

---

## Batch 2 — Security Hardening (HTTP, Images, Gallery)

> Addresses High and Medium security findings: credential leak on redirects, disk exhaustion, path traversal, decompression bombs, and defense-in-depth.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 2.1 | Strip auth headers on cross-origin redirects | Implement a `SafeSession` subclass that overrides `rebuild_auth()` to strip `Authorization`, `Cookie`, `oai-*`, and `Referer` headers when a redirect crosses origins (compare scheme + host + port). Use for both `get_json()` and `stream_download()`. | @python-developer | [security-audit.md](security-audit.md) H-2, [http-resilience.md](http-resilience.md) §5 | — | Medium | Not Started |
| 2.2 | Add download size limit | Add a `max_bytes` parameter to `stream_download()`. Raise `HttpError` when the download exceeds the limit. Default to `100 * 1024 * 1024` (100 MB) for image downloads. Consider a `--max-image-size` CLI flag. | @python-developer | [security-audit.md](security-audit.md) H-3, [http-resilience.md](http-resilience.md) §6 | — | Small | Not Started |
| 2.3 | Path traversal protection on downloads | Add filename sanitization in `incremental_downloader.py` (matching `importer.py`'s `_slugify()` approach) and verify that resolved paths are within the gallery directory via `is_relative_to()`. | @security-auditor | [security-audit.md](security-audit.md) M-3 | — | Small | Not Started |
| 2.4 | Pillow decompression bomb protection | Set `Image.MAX_IMAGE_PIXELS = 200_000_000` at module scope in `thumbnails.py`. Also set it in `ai.py` if/when image resize is added there. | @image-processing-specialist | [security-audit.md](security-audit.md) M-4, [image-pipeline.md](image-pipeline.md) §4 | — | Small | Not Started |
| 2.5 | Add CSP meta tag to gallery | Add `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:;">` to gallery template `<head>`. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) SEC-5 | — | Small | Not Started |
| 2.6 | Strip HTML from AI-generated tags | Add `re.sub(r'<[^>]+>', '', tag)` at tag parse time in `tagger.py` to break the API → metadata → innerHTML XSS chain at source. Also add tag deduplication and lowercase normalization. | @openai-specialist | [openai-integration.md](openai-integration.md) §6, [security-audit.md](security-audit.md) H-1 chain | — | Small | Not Started |
| 2.7 | Use getpass for sensitive interactive inputs | Replace `input()` with `getpass.getpass()` for API key and auth header prompts in `tagger.py` and `utils.py`. Add masked confirmation (e.g., `✓ API key set: sk-Zpp1...`). | @security-auditor | [security-audit.md](security-audit.md) L-2, [openai-integration.md](openai-integration.md) §10 | — | Small | Done |

---

## Batch 3 — Test Infrastructure Foundations

> Foundational test improvements that unblock higher-quality test coverage in later batches.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 3.1 | Create `tests/conftest.py` with shared fixtures | Add `gallery_dir` (tmp_path with images/thumbs subdirectories), `sample_png_bytes` (reusable tiny PNG), and `write_metadata` helpers. Consolidate duplicated `_sample_png()` from 3 files and `_write_metadata()` from 2 files. Add `pytest_configure` with a `slow` marker. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §5, §9 | — | Small | Not Started |
| 3.2 | Mark slow test and exclude from default run | Add `@pytest.mark.slow` to `test_console_script_help_via_built_wheel`. Update `addopts` in `pyproject.toml` to `"-q -m 'not slow'"`. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §9 | 3.1 | Small | Not Started |
| 3.3 | Fix manual env save/restore in test_cli.py | Replace the manual `os.environ.pop` / restore pattern in `test_main_sets_assume_yes` with `monkeypatch.setenv`/`monkeypatch.delenv`. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §4 | — | Small | Not Started |
| 3.4 | Replace lambda mocks with Mock(spec=...) | In `test_tagger.py`, replace `lambda *a, **k: (...)` patterns for `generate_tags` and `ensure_tagging_config` with `Mock(spec=target_function)`. Keep `SimpleNamespace` for OpenAI client mocks. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §3, [openai-integration.md](openai-integration.md) Test Coverage | — | Small | Not Started |
| 3.5 | Create ThumbnailError exception | Add `class ThumbnailError(RuntimeError)` to `thumbnails.py`. Update `create_thumbnails()` to raise `ThumbnailError` instead of wrapping in generic `RuntimeError`. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §5.2, [code-quality-architecture.md](code-quality-architecture.md) §3 | — | Small | Not Started |

---

## Batch 4 — Batch Error Recovery & Resilience

> Fixes the #1 cross-report finding: a single bad image/API call aborts the entire batch.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 4.1 | Fix batch abort in `thumbnails.py` parallel path | Wrap `future.result()` in try/except in `regenerate_thumbnails()`. Collect errors and route them through `StatusReporter.report_error()`. Apply same fix to the serial path. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §3 & §5, [code-quality-architecture.md](code-quality-architecture.md) §9 | 3.5 (ThumbnailError) | Small | Not Started |
| 4.2 | Fix batch abort in `tagger.py` thread pool | Wrap `fut.result()` in try/except in `tag_images()`. Collect errors, log failures, continue processing. Route errors through `StatusReporter.report_error()`. | @openai-specialist | [openai-integration.md](openai-integration.md) §4 & §11, [security-audit.md](security-audit.md) M-6 | — | Small | Not Started |
| 4.3 | Add error-path tests for thumbnails | Write tests for missing source file (`FileNotFoundError`), corrupt image (`UnidentifiedImageError`), and batch behavior with one bad + one good image. Parametrize over `max_workers=[1, 2]` to cover serial and parallel. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 items 4–5, [image-pipeline.md](image-pipeline.md) §11.2 | 3.1 (conftest.py), 3.5, 4.1 | Medium | Not Started |
| 4.4 | Add tagger batch failure isolation test | Submit 3 items where item 2's `generate_tags` raises. Verify items 1 and 3's tags are saved. Test both pre-fix (abort behavior) and post-fix expectations. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 7, [openai-integration.md](openai-integration.md) Test Coverage | 3.1 (conftest.py), 4.2 | Medium | Not Started |
| 4.5 | Periodic metadata save during batch tagging | In `tagger.py`, save metadata every N images (e.g., 10) during the tagging loop rather than only after loop completion, to avoid total data loss on interruption. | @openai-specialist | [openai-integration.md](openai-integration.md) §11 | 4.2 | Medium | Not Started |

---

## Batch 5 — Documentation P0: Accuracy & Onboarding

> Fixes factual errors and major documentation gaps that affect every new user.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 5.1 | Fix `httpx` → `requests` in README | Change "wraps `httpx`" to "wraps `requests`" in the Architecture Overview (line ~259). | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §2 | — | Small | Not Started |
| 5.2 | Reconcile `chat.openai.com` → `chatgpt.com` | Update README auth.txt example, prerequisites, and instructions to use `chatgpt.com`. Update the credential-handling skill file similarly. Match `auth.txt.example`. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §2 | — | Small | Not Started |
| 5.3 | Document `extract-auth` command in README | Add `extract-auth` as the primary macOS auth method. Include `--browser`, `--output`, `--dry-run`, `--no-verify` flags. Present manual auth extraction as the fallback. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §1, §10 | — | Medium | Not Started |
| 5.4 | Add "View your gallery" step to README | After download instructions, add an explicit step: serve the gallery via `python -m http.server 8000` and open `http://localhost:8000/`. Explain that `file://` protocol won't work with `fetch()`. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §10 | — | Small | Not Started |
| 5.5 | Add gallery `file://` troubleshooting entry | Add a troubleshooting section entry for blank gallery when opened by double-clicking. Explain `fetch()` doesn't work over `file://` and provide HTTP serving alternative. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §6, [gallery-ux-accessibility.md](gallery-ux-accessibility.md) E-5 | — | Small | Not Started |
| 5.6 | Add `metadata.json` hosting warning | Add a warning in the README gallery section that `metadata.json` contains signed download URLs and internal file IDs, and should not be publicly hosted. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §15, [security-audit.md](security-audit.md) M-2 | — | Small | Not Started |

---

## Batch 6 — Gallery Accessibility: Critical & High

> Addresses WCAG A and AA violations. Prerequisite: Batch 2 XSS fix means card construction is already refactored to DOM API.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 6.1 | Add `<meta name="viewport">` tag | Add `<meta name="viewport" content="width=device-width, initial-scale=1">` to `<head>`. Without it, mobile renders at ~980px width. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) R-1 | — | Small | Done |
| 6.2 | Add skip-to-content link | Add `<a class="skip-link" href="#gallery">Skip to content</a>` as the first focusable element in `<body>`. Style it to be visually hidden until focused. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-1 | — | Small | Done |
| 6.3 | Lightbox focus management & ARIA | On open: move focus to viewer, add `role="dialog"`, `aria-modal="true"`, `aria-label`. Trap Tab within the viewer. On close: return focus to the triggering card. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-2, A-3, L-1, L-2 | — | Medium | Done |
| 6.4 | Make all controls keyboard-accessible | Change dark mode toggle from `<div>` to `<button>`. Add `role="button"` and `keydown` handler to search help icon. Replace inline `onclick` handlers with `addEventListener`. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-4, J-3 | — | Medium | Done |
| 6.5 | Add `:focus-visible` styles | Add visible focus indicators for all interactive elements: links, buttons, inputs, select, gallery cards. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-5, A-6 | — | Small | Done |
| 6.6 | Make metadata accessible without hover | Add `:focus-within .meta { display: block }` CSS rule. Consider always-visible title below cards in list/full views. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-7, M-1 | — | Small | Done |
| 6.7 | Handle fetch errors gracefully | Wrap `loadImages()` in try/catch, show a user-friendly error message in the gallery container. Add `.catch()` to the promise chain. Add `<noscript>` message. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) E-1, E-5, J-5, S-4 | — | Small | Done |

---

## Batch 7 — API & HTTP Resilience Improvements

> Expand error handling, fix double-retry, add timeouts and cost controls.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 7.1 | Catch transient OpenAI errors in retry loop | Add `APIConnectionError`, `APITimeoutError`, and `InternalServerError` to the retry catch in `call_image_endpoint()`. Extract a `_is_transient(exc)` helper for testability. | @openai-specialist | [openai-integration.md](openai-integration.md) §2 & §4 | — | Small | Done |
| 7.2 | Set `max_retries=0` on OpenAI SDK client | Prevent double-retry (SDK default 2 × code's 3 = 6). Set in `get_cached_client()`. | @openai-specialist | [openai-integration.md](openai-integration.md) §1 | — | Small | Done |
| 7.3 | Add `AuthenticationError` / `BadRequestError` handling | Catch `AuthenticationError` early with a clear "Invalid API key" message. Catch `BadRequestError` to skip content-filtered images gracefully. | @openai-specialist | [openai-integration.md](openai-integration.md) §4 | — | Small | Done |
| 7.4 | Validate `response.output_text` before accessing | Guard against `output_text=None` (content-filtered response) which currently raises `AttributeError`. Return a clear error or empty result. | @openai-specialist | [openai-integration.md](openai-integration.md) §4, [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 6 | — | Small | Done |
| 7.5 | Set `max_tokens` on API calls | Set `max_tokens=300` for tagging, `max_tokens=50` for renaming in `call_image_endpoint()`. | @openai-specialist | [openai-integration.md](openai-integration.md) §5 | — | Small | Done |
| 7.6 | Increase HTTP backoff factor to 1.0 | Change `backoff_factor=0.5` to `1.0` in `HttpClient._create_session()` to match the skill and provide more respectful retry behavior for 429 responses. | @python-developer | [http-resilience.md](http-resilience.md) §1, §12 | — | Small | Done |
| 7.7 | Split connect/read timeouts | Change `HttpClient.__init__` to accept `connect_timeout` and `read_timeout` separately. Use `timeout=(10.0, 60.0)` as default. | @python-developer | [http-resilience.md](http-resilience.md) §3 | — | Small | Done |

---

## Batch 8 — Code Architecture & Type Safety

> Introduce typed configs, centralize constants, and remove dead code.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 8.1 | Create `TaggingConfig` dataclass | Replace the raw `dict` returns in `tagger.py` (`_load_config`, `_write_config`, `ensure_tagging_config`) and `ai.py` (`resolve_config`) with a typed `TaggingConfig` dataclass. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §2 & §6 | — | Medium | Not Started |
| 8.2 | Create `AuthConfig` TypedDict | Replace raw `dict` returns in `utils.py` (`load_auth_config`, `prompt_and_write_auth`, `ensure_auth_config`) with a `TypedDict`. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §2 & §6 | — | Small | Not Started |
| 8.3 | Centralize `DEFAULT_MODEL` constant | Define `DEFAULT_MODEL = "gpt-4.1-mini"` once in `ai.py` and import it everywhere instead of duplicating the string literal in `ai.py`, `tagger.py`, and `importer.py`. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §6 | — | Small | Not Started |
| 8.4 | Add `from __future__ import annotations` to missing files | Add to `__init__.py`, `cli/__init__.py`, `utils.py`, and `gallery.py`. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §2 | — | Small | Not Started |
| 8.5 | Remove duplicate `parse_args()`/`main()` | Remove standalone `parse_args()` and `main()` from `importer.py` and `tagger.py`. These duplicate the CLI commands and are dead code after the CLI refactor. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §1, §5 | — | Small | Not Started |
| 8.6 | Extract `_DEFAULT_USER_AGENT` constant | In `browser_extract.py`, extract the hardcoded User-Agent string (duplicated 3 times) to a module-level `_DEFAULT_USER_AGENT` constant. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §5 | — | Small | Not Started |

---

## Batch 9 — CI/CD Pipeline Hardening

> Improve build reproducibility, test matrix, and security scanning.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 9.1 | Add Python version matrix to CI | Test on `[3.10, 3.11, 3.12, 3.13]` in GitHub Actions. The project declares `>=3.10` but only tests on latest. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §4 | — | Small | Done |
| 9.2 | Add pip caching to CI | Enable `cache: 'pip'` in `actions/setup-python` to avoid reinstalling all deps on every run. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §4 | — | Small | Done |
| 9.3 | Generate pinned dependency lock files | Run `pip-compile` or `uv pip compile` to produce fully-pinned `requirements.txt` and `requirements-dev.txt`. Commit them. Update Makefile sync targets accordingly. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §2 | — | Medium | Done |
| 9.4 | Add `pip-audit` to CI | Add `pypa/gh-action-pip-audit@v1` as a CI job to catch known dependency vulnerabilities. | @security-auditor | [devops-ci-pipeline.md](devops-ci-pipeline.md) §10 | — | Small | Done |
| 9.5 | Enable ruff `S` (bandit security) rules | Add `"S"` to the ruff `select` list in `pyproject.toml`. Add per-file ignores for known-safe subprocess patterns in `browser_extract.py` and `bootstrap.py`. | @security-auditor | [devops-ci-pipeline.md](devops-ci-pipeline.md) §5, §10 | — | Small | Done |
| 9.6 | Add pre-commit CI job | Add a workflow step (or use pre-commit.ci) that runs `pre-commit run --all-files` in CI to enforce formatting hooks. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §4 | 1.6 (ruff version fix) | Small | Done |
| 9.7 | Add build verification to CI | Add a job that runs `make build`, installs the wheel in a fresh venv, and verifies `chatgpt-archiver --help` works and `gallery_index.html` is packaged. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §4 | — | Medium | Done |

---

## Batch 10 — Test Coverage Expansion

> Fill the highest-priority test gaps identified across all reviews.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 10.1 | Corrupt/malformed metadata JSON tests | Test `load_gallery_items` with truncated JSON, non-list root, items missing `id`/`filename`, and non-dict items in list. Verify silent-skip behavior. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 1 | 3.1 | Small | Done |
| 10.2 | HTTP streaming failure test | Mock `iter_content` to raise mid-stream. Verify partial file cleanup (`destination.unlink()`). | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 2, [http-resilience.md](http-resilience.md) §13 | — | Small | Done |
| 10.3 | Empty response body rejection test | Test `stream_download()` with zero bytes received when `allow_empty=False` (default). | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 3 | — | Small | Done |
| 10.4 | Thumbnail format-specific tests | Parametrize tests for WebP, GIF, BMP input images through `create_thumbnails` to cover `_prepare_for_format` branches. Test RGBA→RGB conversion for JPEG. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 4, [image-pipeline.md](image-pipeline.md) §11.3 | 3.1 | Medium | Done |
| 10.5 | `output_text=None` crash test | Mock `responses.create` to return `SimpleNamespace(output_text=None, usage=...)`. Verify `call_image_endpoint` handles gracefully (after 7.4 fix). | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 6, [openai-integration.md](openai-integration.md) Test Coverage | 7.4 | Small | Done |
| 10.6 | Parametrized OpenAI error type tests | Parametrize over `TRANSIENT_ERRORS = [RateLimitError, APIConnectionError, APITimeoutError]` (should retry) and `FATAL_ERRORS = [AuthenticationError, BadRequestError]` (should raise). | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 8, [openai-integration.md](openai-integration.md) §4 | 7.1, 7.3 | Medium | Done |
| 10.7 | Unicode filename and _slugify tests | Test `_slugify` and `_unique_filename` in `importer.py` with Unicode input, empty input, and collision scenarios. | @testing-expert | [test-coverage-strategy.md](test-coverage-strategy.md) §6 item 9 | — | Small | Done |

---

## Batch 11 — Gallery UX: Navigation & Performance

> Addresses the most impactful usability improvements for a 1,169-image gallery.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 11.1 | Implement client-side pagination | Add pagination (e.g., 100 items per page with infinite scroll or page buttons). Currently all 1,169 items render at once, creating ~4,700+ DOM elements. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) P-1, N-1 | 6.x (accessibility base) | Large | Not Started |
| 11.2 | Debounce `filterGallery()` | Add 200ms debounce on the search `oninput` handler to prevent per-keystroke filtering of 1,169 items. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) P-3 | — | Small | Not Started |
| 11.3 | Batch DOM construction with DocumentFragment | Build all cards into a `DocumentFragment` before appending to the gallery container, reducing reflow triggers. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) P-4 | — | Small | Not Started |
| 11.4 | Add semantic HTML | Wrap gallery in `<main>`, controls in `<nav>`, cards in `<article>` or `<figure>`/`<figcaption>`. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-8 | — | Small | Not Started |
| 11.5 | Add sort controls | Add UI controls for sorting by date (ascending/descending) and title (A-Z). | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) N-2 | — | Medium | Not Started |
| 11.6 | Show result count after filtering | Display "Showing X of Y images" after filtering. Add `aria-live` region for screen reader announcement. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) N-3, A-12 | — | Small | Not Started |
| 11.7 | Add clickable tags | Make tags in the metadata overlay clickable to pre-fill the search input with that tag. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) N-5 | — | Medium | Not Started |

---

## Batch 12 — Function Decomposition & Data Flow

> Break up the highest-complexity functions and fix data flow issues. Improves testability and maintainability.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 12.1 | Decompose `import_images()` with `ImportConfig` | Group the 17 parameters into an `ImportConfig` dataclass. Extract file-collection and AI-rename logic into focused helper functions. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §1, §4 | 8.1 (TaggingConfig pattern) | Large | Done |
| 12.2 | Extract `download_image` closure to top-level | Move the `download_image()` closure from inside `incremental_downloader.main()` to a top-level function. Have it return a result DTO instead of mutating `GalleryItem`. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §4, §9 | — | Medium | Done |
| 12.3 | Split `tag_images()` into generate and remove | Separate `tag_images()` into `tag_images()` (generate only) and `remove_tags()`. The current function conflates both operations via boolean flags. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §11 | — | Medium | Done |
| 12.4 | Decompose `regenerate_thumbnails()` | Split into `ensure_thumbnail_metadata()` (lightweight metadata-only fixup) and `regenerate_thumbnails()` (full generation). The downloader would call the metadata function after per-image creation. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §8.1 | — | Medium | Done |
| 12.5 | Save metadata incrementally in download loop | Move `save_gallery_items()` inside the pagination loop in `incremental_downloader.main()` so progress is saved per-page rather than only after all downloads complete. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §8 | 1.4 (atomic writes) | Small | Done |

---

## Batch 13 — Image Pipeline & AI Cost Optimization

> Performance, cost, and memory improvements for image processing.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 13.1 | Resize images before AI encoding | Enhance `encode_image()` in `ai.py` to use Pillow (already a dependency) to resize images >500KB to ≤1024px before base64 encoding. Apply EXIF transpose. Convert BMP/TIFF to JPEG. Estimated 60–80% token cost savings. | @openai-specialist, @image-processing-specialist | [openai-integration.md](openai-integration.md) §8, [image-pipeline.md](image-pipeline.md) §12 | 2.4 (MAX_IMAGE_PIXELS) | Medium | Not Started |
| 13.2 | Cap `max_workers` in ProcessPoolExecutor | Default to `min(os.cpu_count(), 8)` when `max_workers` is None, to prevent excessive memory usage on large machines. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §3 | — | Small | Not Started |
| 13.3 | Add mtime-based freshness check | Compare source image `st_mtime` against thumbnail `st_mtime` in `regenerate_thumbnails()`. Regenerate if source is newer. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §8 | — | Small | Not Started |
| 13.4 | RGBA → RGB white background compositing | When converting RGBA to JPEG, composite onto a white background instead of defaulting to black. Benefits both thumbnails and AI encoding. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §6 | — | Small | Not Started |
| 13.5 | Explicitly close intermediate images | Close `thumb` and `prepared` images explicitly after saving in `create_thumbnails()` to reduce peak memory in the process pool. | @image-processing-specialist | [image-pipeline.md](image-pipeline.md) §9 | — | Small | Not Started |
| 13.6 | Make download `max_workers` configurable | Expose as a CLI argument for `download` command. Lower default from 14 to 6. | @python-developer | [http-resilience.md](http-resilience.md) §11 | — | Small | Not Started |

---

## Batch 14 — Pyright Expansion & Linting

> Incrementally expand static analysis coverage.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 14.1 | Expand pyright to `status.py`, `utils.py`, `ai.py` | Add these three modules to the pyright `include` list. Fix any type errors surfaced. These are the easiest modules to make strict-compatible. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §2, [devops-ci-pipeline.md](devops-ci-pipeline.md) §5 | 8.1, 8.2 (typed configs) | Medium | Not Started |
| 14.2 | Expand pyright to `http_client.py`, `gallery.py` | Add to pyright include. Fix type errors. These modules have clean signatures already. | @python-developer | [code-quality-architecture.md](code-quality-architecture.md) §2 | 14.1 | Medium | Not Started |
| 14.3 | Expand pyright to `thumbnails.py` | Add to pyright include. This module has more complex types due to Pillow, but is well-structured. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §5 | 14.2 | Medium | Not Started |
| 14.4 | Add `PTH` (pathlib) rule set to ruff | Add the `PTH` rule set to encourage pathlib usage. Migrate `bootstrap.py` from `os.path` to `pathlib`. Fix remaining `os.path` usage in `gallery.py` and `tagger.py`. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §5, [code-quality-architecture.md](code-quality-architecture.md) §10 | — | Medium | Not Started |
| 14.5 | Add pytest markers and reduce coverage omit list | Add `@pytest.mark.slow` and `@pytest.mark.integration` markers. Progressively reduce the coverage omit list by adding tests for `cli/` and other excluded modules. | @testing-expert | [devops-ci-pipeline.md](devops-ci-pipeline.md) §6, [test-coverage-strategy.md](test-coverage-strategy.md) §1 | 3.1, 3.2 | Medium | Not Started |

---

## Batch 15 — Documentation & Skill File Updates

> Update skill files to match actual code, expand agent guidance.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 15.1 | Update `openai-vision-api` skill file | Replace `chat.completions.create` with `responses.create`. Update content type keys to `input_text`/`input_image`. Update mock examples. This is the most outdated skill. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §7 | 7.x (API changes) | Medium | Not Started |
| 15.2 | Update `archiver-testing-strategy` skill | Fix OpenAI mock example to use `responses.create`. Update mock strategy table: `SimpleNamespace` for OpenAI client, `Mock(spec=...)` for project functions. Add `test_browser_extract.py` to file listing. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §7, [test-coverage-strategy.md](test-coverage-strategy.md) §10 | — | Small | Not Started |
| 15.3 | Update credential-handling skill domain | Change `chat.openai.com` to `chatgpt.com`. Add `extract-auth` as a credential acquisition method. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §7 | — | Small | Not Started |
| 15.4 | Expand `AGENTS.md` | Add Python version (3.10+), pointer to skill files in `.github/skills/`, coverage threshold (85%), security-sensitive files list (`auth.txt`, `tagging_config.json`). | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §8 | — | Small | Not Started |
| 15.5 | Create `docs/adr/README.md` | Create the ADR directory and index file so the ADR skill's references work. Include a template link and numbering convention. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §5, §7 | — | Small | Not Started |
| 15.6 | Document `--browser` download flag | Add the `--browser edge|chrome` flag documentation to the README `download` command section. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §1, §12 | — | Small | Not Started |
| 15.7 | Document `ARCHIVER_ASSUME_YES` env var | Add to README for CI/scripted use. Currently only in `utils.py` docstring and credential skill. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §4 | — | Small | Not Started |
| 15.8 | Add privacy/consent notice for `tag` command | Document in README and `tag --help` that images are sent to OpenAI's vision API for analysis. Consider a consent prompt suppressible via `ARCHIVER_ASSUME_YES`. | @documentation-specialist | [documentation-quality.md](documentation-quality.md) §1, [openai-integration.md](openai-integration.md) §10 | — | Small | Not Started |

---

## Batch 16 — Gallery Visual Polish

> Lower-priority UX improvements, error states, and cleanup.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 16.1 | Remove legacy `page_*.html` files | Delete `gallery/page_1.html` and `gallery/page_2.html`. These are orphaned legacy pages not generated by current code. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) S-1 | — | Small | Not Started |
| 16.2 | Add lightbox prev/next buttons | Add visible on-screen arrow buttons for mouse/touch navigation in the lightbox (currently only keyboard arrows and swipe work). | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) L-4 | 6.3 | Medium | Not Started |
| 16.3 | Add lightbox image counter | Show "3 of 47" (or filtered count) in the lightbox. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) L-5 | — | Small | Not Started |
| 16.4 | Add card borders/shadows in light mode | Add a subtle `box-shadow` or `border` to cards so white images don't blend into the white background. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) V-1 | — | Small | Not Started |
| 16.5 | Use system font stack | Replace bare `sans-serif` with `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) V-2 | — | Small | Not Started |
| 16.6 | Show empty/filtered-to-zero messages | When the gallery is empty or all items are filtered out, show a "No images found" / "No matching images" message. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) E-3, E-4 | — | Small | Not Started |
| 16.7 | Add broken image fallback | Add an `onerror` handler on `<img>` elements to show a placeholder or hide the card when thumbnails/images fail to load. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) E-2 | — | Small | Not Started |
| 16.8 | Wrap all JS in an IIFE | Wrap the `<script>` contents in an IIFE to avoid global scope pollution. Replace inline `onclick`/`oninput` with `addEventListener`. | @gallery-ux-designer | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) J-2 | 6.4 | Small | Not Started |

---

## Batch 17 — Release Infrastructure & DevOps Polish

> Establish a release process and developer experience improvements.

| # | Title | Description | Agent(s) | Reference | Depends On | Complexity | Status |
|---|-------|-------------|----------|-----------|------------|------------|--------|
| 17.1 | Add GitHub Actions release workflow | Trigger on tag push (`v*`). Build and publish to PyPI via `pypa/gh-action-pypi-publish`. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §7 | 9.7 (build verification) | Medium | Not Started |
| 17.2 | Adopt single-source versioning | Use `setuptools-scm` or `hatch-vcs` to derive version from git tags, eliminating dual maintenance in `pyproject.toml` and `__init__.py`. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §7 | — | Medium | Not Started |
| 17.3 | Add CHANGELOG.md | Create a changelog tracking notable changes. Consider automated generation from conventional commits. | @documentation-specialist | [devops-ci-pipeline.md](devops-ci-pipeline.md) §7, [documentation-quality.md](documentation-quality.md) §12 | — | Small | Not Started |
| 17.4 | Add `.gitattributes` | Add `* text=auto` and explicit binary patterns for image files and Pillow-processed outputs. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §9 | — | Small | Not Started |
| 17.5 | Add `.python-version` file | Create `.python-version` (e.g., `3.10`) for pyenv/mise/asdf users. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §8 | — | Small | Not Started |
| 17.6 | Add Makefile convenience targets | Add `make clean` (remove build artifacts), `make fmt` (auto-format), and `make check` (lint + test combined). | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §1 | — | Small | Not Started |
| 17.7 | Unify hook strategy | Decide between pre-commit framework and `.githooks`. Recommended: keep pre-commit framework (with `language: system` ruff from Batch 1.6), remove `.githooks/pre-commit` or convert to pre-push. | @python-developer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §3 | 1.6 | Small | Not Started |

---

## Deferred / Won't Fix

Items from the reviews that are informational only, premature, or intentionally deprioritized.

| Item | Source | Rationale |
|------|--------|-----------|
| Hash API key for cache key (`M-1`) | [security-audit.md](security-audit.md) M-1 | Low practical impact; the `OpenAI` client object itself holds the key in memory. Code hygiene improvement only. |
| Strip signed URLs from persisted metadata (`M-2`) | [security-audit.md](security-audit.md) M-2 | URLs expire quickly and `gallery/` is gitignored. Warning added in Batch 5 is sufficient. |
| Symlink check on downloads (`L-5`) | [security-audit.md](security-audit.md) L-5 | Very low risk; requires attacker write access to gallery dir. |
| Base64 payload in process memory (`L-6`) | [security-audit.md](security-audit.md) L-6 | Inherent to the approach; resize optimization (Batch 13) reduces this. No code fix needed. |
| Resumable downloads (Range headers) | [http-resilience.md](http-resilience.md) §2 | Complexity outweighs benefit for typical image sizes (<10MB). |
| Per-file byte-level download progress | [http-resilience.md](http-resilience.md) §2 | Nice-to-have; current item-level progress is sufficient. |
| Token budget assertion test helper | [test-coverage-strategy.md](test-coverage-strategy.md) §5 | Premature — `max_tokens` parameter doesn't exist yet. Implement alongside 7.5. |
| Image resize verification test helper | [test-coverage-strategy.md](test-coverage-strategy.md) §5 | Premature — depends on encode_image resize (Batch 13.1). |
| Retry-After header test helper | [test-coverage-strategy.md](test-coverage-strategy.md) §5 | Premature — Retry-After parsing not implemented. |
| Optional WebP thumbnail output | [image-pipeline.md](image-pipeline.md) §7 | Future enhancement; current format-matching is sufficient. |
| ICC profile handling / sRGB conversion | [image-pipeline.md](image-pipeline.md) §1 | Minor color accuracy improvement; low priority. |
| `srcset` responsive images in gallery | [image-pipeline.md](image-pipeline.md) §2 | JS-based size switching works; `srcset` is progressive enhancement. |
| SBOM generation | [devops-ci-pipeline.md](devops-ci-pipeline.md) §10 | Premature for v0.1.0 FOSS project. |
| Docker / devcontainer | [devops-ci-pipeline.md](devops-ci-pipeline.md) §8 | Nice-to-have; not needed for current contributor profile. |
| tox/nox multi-version local testing | [devops-ci-pipeline.md](devops-ci-pipeline.md) §8 | CI matrix (Batch 9.1) covers this need. |
| Commitlint enforcement | [devops-ci-pipeline.md](devops-ci-pipeline.md) §9 | Overhead for single-contributor FOSS project. |
| Issue/PR templates | [devops-ci-pipeline.md](devops-ci-pipeline.md) §12 | Add when external contribution begins. |
| CODEOWNERS file | [devops-ci-pipeline.md](devops-ci-pipeline.md) §12 | AI agent team, not human team — not applicable. |
| `detect-private-key` pre-commit hook | [devops-ci-pipeline.md](devops-ci-pipeline.md) §3 | Useful but low urgency with `.gitignore` coverage. Can add alongside Batch 17.7. |
| API reference for programmatic usage | [documentation-quality.md](documentation-quality.md) §11 | Premature for v0.1.0; CLI is the primary interface. |
| Separate `tests/helpers/openai_fakes.py` | [test-coverage-strategy.md](test-coverage-strategy.md) §5 | Over-engineering for current project size; `conftest.py` is sufficient. |
| Content-Length vs actual bytes validation | [http-resilience.md](http-resilience.md) §2 | Low-frequency issue; checksum validation catches corruption. |
| Cost estimation in telemetry summary | [openai-integration.md](openai-integration.md) §9 | Nice-to-have; token counts are already reported. |
| Persistent telemetry log file | [openai-integration.md](openai-integration.md) §9 | Adds file management complexity for marginal benefit. |
| Thread safety of `_CLIENT_CACHE` | [security-audit.md](security-audit.md) M-1 cross-review | GIL makes dict ops safe in practice; `functools.lru_cache` alternative adds complexity. |
| System prompt for tagging/renaming | [openai-integration.md](openai-integration.md) §3 | Minor improvement; current prompts work well. |
| Simplify `_entry_get`/`_entry_set` to GalleryItem-only | [image-pipeline.md](image-pipeline.md) §10.1 | dict path used by tests; low priority code hygiene. |
| `select#sizeSelector` label association (A-9) | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-9 | Include as part of Batch 6 or 11 work as a quick fix. |
| Gallery `alt` text fallback to filename (A-10) | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) A-10 | Quick win; include with Batch 1.3 (XSS refactor) since `alt` is being rebuilt. |
| Lightbox loading indicator (L-7) | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) L-7 | Polish; include with Batch 16. |
| Lightbox transition animation (V-5) | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) V-5 | Polish; include with Batch 16. |
| Dark mode toggle visibility on mobile (D-4) | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) D-4 | Address with Batch 16 or gallery redesign. |
| Log swallowed AI rename exception | [code-quality-architecture.md](code-quality-architecture.md) §3 | Include as part of Batch 4/12 decomposition work. |

---

## Appendix: Review Document Index

| # | Document | Primary Agent(s) | Findings |
|---|----------|-----------------|----------|
| 1 | [security-audit.md](security-audit.md) | @security-auditor | 2 Critical, 4 High, 6 Medium, 6 Low, 4 Info |
| 2 | [code-quality-architecture.md](code-quality-architecture.md) | @python-developer | 12 sections, 5 modules with complexity suppressions |
| 3 | [test-coverage-strategy.md](test-coverage-strategy.md) | @testing-expert | 136 tests, 91% coverage, 17 missing test items |
| 4 | [gallery-ux-accessibility.md](gallery-ux-accessibility.md) | @gallery-ux-designer | 6 Critical, 13 High, 20 Medium, 15 Low |
| 5 | [image-pipeline.md](image-pipeline.md) | @image-processing-specialist | 17 recommendations across P1–P3 |
| 6 | [openai-integration.md](openai-integration.md) | @openai-specialist | 23 items across Critical–Low |
| 7 | [http-resilience.md](http-resilience.md) | @python-developer | 13 recommendations across P1–P4 |
| 8 | [documentation-quality.md](documentation-quality.md) | @documentation-specialist | 23 items across P0–P3 |
| 9 | [devops-ci-pipeline.md](devops-ci-pipeline.md) | @python-developer | 20 items across Critical–Low |
