# Documentation Quality Review

**Project:** chatgpt-library-archiver
**Date:** 2026-03-01
**Updated:** 2026-03-01 (incorporated cross-review findings)
**Scope:** All documentation files, skill files, inline documentation, and configuration examples

---

## Executive Summary

The project has **above-average documentation for its scale**. The README is comprehensive, covering setup through advanced usage. Skill files provide substantial depth for AI agents. However, several **factual inaccuracies** have crept in as the codebase evolved, there are **undocumented features**, and some areas have **domain inconsistencies** that could confuse both human users and automated agents.

Cross-review input from the UX and synthesis perspectives surfaced two key insights this review originally underweighted:

- **`extract-auth` is the single highest-impact documentation fix.** The UX review makes a compelling case: it transforms the auth setup from a fragile 7-step manual process into a single command. Most CLI tool abandonment happens during initial setup, making this a user-retention issue, not just a completeness gap.
- **Documentation gaps have security-preventing value.** The synthesis identified 12 documentation items that, if they existed, would prevent users from making dangerous misconfigurations — a framing this review didn't apply to its findings.

**Top priorities:**
1. Fix factual inaccuracy: README claims `http_client.py` wraps `httpx` when it actually wraps `requests` (P0)
2. Reconcile `chat.openai.com` vs `chatgpt.com` domain inconsistencies across all docs (P0)
3. Remove/replace real API key in working-tree `tagging_config.json` (P0 — elevated from P3 per synthesis)
4. Document the `extract-auth` command as the primary macOS auth method in the README (P0 — elevated from P1 per UX review)
5. Document `--browser` download flag and add explicit "view your gallery" step (P1)
6. Update OpenAI vision API skill to reflect actual `responses.create` API usage (P1)
7. Add warning about not publicly hosting `metadata.json` (P1 — new, from security-preventing documentation analysis)

---

## 1. README Completeness

### Strengths

- **Comprehensive structure**: Covers setup, authentication, script usage, architecture, troubleshooting, testing, contributing, and licensing — all the sections a user needs.
- **Multiple setup paths**: Documents bootstrap, manual, and Makefile-based installation. Also covers `uv` and `pip-tools` for CI environments.
- **Architecture section**: Provides a module-by-module breakdown of responsibilities that is genuinely useful for onboarding (lines 242–310).
- **Quality gates**: Clearly documents `make lint` and `make test` expectations.
- **Gallery viewer features**: Thorough description of the browser-based gallery including keyboard shortcuts, dark mode, and filtering.
- **Disk space estimates**: Practical guidance for storage planning.

### Gaps

| Gap | Severity | Details |
|-----|----------|---------|
| `extract-auth` command undocumented | High | A full subcommand (`extract-auth`) exists for automatically extracting credentials from Edge/Chrome on macOS. It supports `--browser`, `--output`, `--dry-run`, and `--no-verify` flags. No mention in README. |
| `--browser` flag on `download` undocumented | High | The download command accepts `--browser edge|chrome` to use live browser credentials instead of `auth.txt`. Not mentioned in README. |
| `browser_extract.py` module undocumented | Medium | The browser credential extraction module (509 lines) has no mention in the Architecture Overview. |
| No changelog or release history | Low | Version is `0.1.0`; as the project matures, a CHANGELOG would help track evolution. |
| No "Uninstallation" section | Low | Minor but helpful for users who want to clean up. |
| No "view your gallery" step in happy path | Medium | After download completes, the README never explicitly says "open `gallery/index.html` in your browser." The UX cross-review identifies this as a journey-breaking gap — users reach the payoff moment and don't know what to do next. |
| No warning about publicly hosting `metadata.json` | High | Contains signed download URLs and internal file IDs. The synthesis identifies this as security-preventing documentation. |
| No privacy/consent notice for `tag` command | Medium | The `tag` command sends images to OpenAI's vision API without notification. The UX review recommends a consent prompt, suppressible via `ARCHIVER_ASSUME_YES`. |

---

## 2. README Accuracy Issues

### Critical: `httpx` vs `requests`

The Architecture Overview at [line 259](README.md#L259) states:

> `chatgpt_library_archiver/http_client.py` – wraps `httpx` with checksums, strict content-type validation, and streaming support

**Actual code** ([http_client.py](src/chatgpt_library_archiver/http_client.py#L11-L13)):
```python
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
```

The module wraps `requests`/`urllib3`, not `httpx`. Additionally, `pyproject.toml` lists `requests>=2.31.0` as a dependency, not `httpx`.

### Critical: Domain Inconsistency (`chat.openai.com` vs `chatgpt.com`)

The README uses `chat.openai.com` throughout (auth.txt examples at lines 99–106, browser instructions at line 110, prerequisites at line 38), but the actual code and `auth.txt.example` use `chatgpt.com`:

| Location | Domain Used |
|----------|-------------|
| [auth.txt.example](auth.txt.example) | `chatgpt.com` |
| [browser_extract.py](src/chatgpt_library_archiver/browser_extract.py#L35-L36) | `chatgpt.com` |
| [incremental_downloader.py](src/chatgpt_library_archiver/incremental_downloader.py#L201) | `chat.openai.com` (conversation links) |
| [README.md](README.md#L99) auth.txt example | `chat.openai.com` |
| [README.md](README.md#L38) prerequisites | `chat.openai.com` |
| [credential-handling SKILL.md](.github/skills/credential-handling/SKILL.md#L24) | `chat.openai.com` |

The `auth.txt.example` (the canonical source) uses `chatgpt.com`, suggesting the README and skill file are outdated. Both domains currently work (OpenAI redirects), but documentation should match the example file.

### Minor: `tagging_config.json` Example

The README example at lines 136–141 shows:

```json
{
  "api_key": "sk-...",
  "model": "gpt-4.1-mini",
  "prompt": "Generate concise, comma-separated tags describing this image.",
  "rename_prompt": "..."
}
```

The actual `tagging_config.json` in the repository has a much longer, more detailed prompt. While the README example is meant to be illustrative, noting that the default prompt is more comprehensive would set expectations correctly.

---

## 3. Inline Documentation Quality

### Module Docstrings

| Module | Has Docstring? | Quality |
|--------|---------------|---------|
| `ai.py` | Yes | Good — "Shared helpers for working with the OpenAI client." |
| `http_client.py` | Yes | Good — "HTTP utilities with retry/backoff, streaming downloads, and validation." |
| `incremental_downloader.py` | Yes | Good — "Incremental downloader for ChatGPT image library assets." |
| `gallery.py` | No | **Missing** — file has no module docstring |
| `thumbnails.py` | Yes | Good — "Helpers for creating and maintaining gallery thumbnails." |
| `metadata.py` | Yes | Good — "Typed models and helpers for gallery metadata persistence." |
| `status.py` | Yes | Good — "Utilities for consistent status logging and progress bars." |
| `utils.py` | No | **Missing** — file starts with bare `import os` |
| `browser_extract.py` | Yes | Excellent — multi-line docstring explaining purpose, mechanism, and dependencies |
| `__init__.py` | Yes | Good — "Top-level package for ChatGPT Library Archiver." |
| `__main__.py` | Yes | Good — "Unified command-line interface for ChatGPT Library Archiver." |
| `cli/app.py` | Yes | Good — "Command-line application wiring for the archiver CLI." |
| `cli/commands/extract_auth.py` | Yes | Good — "CLI command for extracting auth credentials from a browser." |
| `cli/commands/download.py` | Yes | Good — "Download command implementation." |

**Coverage: 12/14 modules** have module-level docstrings — good overall.

### Function/Class Docstrings

Public API docstring coverage is strong in the core modules:

- **`ai.py`**: All public functions documented (`get_cached_client`, `reset_client_cache`, `resolve_config`, `encode_image`, `call_image_endpoint`). `AIRequestTelemetry` fields are self-documenting via the class docstring.
- **`http_client.py`**: `get_json` and `stream_download` have detailed docstrings. `HttpError`, `DownloadResult` documented. `HttpClient.__init__` parameters are not documented but are self-explanatory.
- **`metadata.py`**: All public functions and `GalleryItem` fields documented. `from_dict` and `to_dict` have clear one-liners.
- **`thumbnails.py`**: `thumbnail_relative_path` has a NumPy-style docstring with `Parameters` section — the only module using this style, creating a minor inconsistency. `create_thumbnails` and `regenerate_thumbnails` are documented.
- **`status.py`**: `StatusReporter` methods all have docstrings.
- **`utils.py`**: `prompt_yes_no` has a complete docstring with Args/Returns sections. `load_auth_config` has a brief docstring. `ensure_auth_config` and `prompt_and_write_auth` lack docstrings.

### Inline Comments

Code comments are sparse but generally follow the "why not what" principle. Notable examples:
- `http_client.py`: No inline comments needed — code is self-explanatory.
- `thumbnails.py`: `_LANCZOS` fallback comment explains Pillow version compatibility.
- `incremental_downloader.py`: Progress flow comments at key decision points.

**Assessment**: Inline documentation is **good** overall, with minor gaps in `utils.py` and `gallery.py`.

---

## 4. Configuration Documentation

### `auth.txt`

- **README coverage**: Well-documented with step-by-step browser instructions (lines 94–120).
- **Example file**: `auth.txt.example` exists and is accurate.
- **Issue**: Domain mismatch between README example and actual example file (see §2).
- **Security guidance**: File permissions (`600`) and `.gitignore` inclusion are documented.

### `tagging_config.json`

- **README coverage**: Documents all keys, defaults, and environment variable overrides (lines 129–165).
- **Non-interactive configuration**: Fully documented with environment variable names.
- **Issue**: The actual `tagging_config.json` in the repo contains what appears to be a real API key (`sk-REDACTED`). Even if revoked, this is a poor practice — the file should either not exist or use a placeholder like `sk-...`.
- **`.gitignore` status**: Listed in `.gitignore`, so it won't be committed — but it currently exists in the working tree.

### Missing Configuration Documentation

- The `ARCHIVER_ASSUME_YES` environment variable is documented in `utils.py` docstring and the credential skill, but **not in the README**.
- The `--no-config-prompt` flag is mentioned in the README (line 158) but its exact behavior isn't described.

---

## 5. Architecture Documentation

### Strengths

- The README Architecture Overview (lines 242–310) is genuinely excellent:
  - Covers every module with a concise responsibility description
  - Explains the gallery data layout with a visual directory tree
  - Documents `metadata.json` fields comprehensively
  - Notes the composable, independent-evolution design philosophy

### Gaps

- **No data flow diagram**: While the module descriptions are clear, a visual showing how data flows from API → download → metadata → thumbnails → gallery would help.
- **`browser_extract.py` omitted**: This 509-line module is not mentioned in the Architecture Overview despite being a significant feature.
- **No ADR directory**: The ADR skill file references `docs/adr/` and `docs/adr/README.md`, but **neither exists**. No architecture decisions have been formally recorded.
- **No module dependency diagram**: Understanding which modules import which would help contributors.

---

## 6. Error/Troubleshooting Documentation

### Current Coverage

The Troubleshooting section (README lines 347–354) covers only three scenarios:
1. `403`/`401` token expiry → refresh `auth.txt`
2. Interactive re-credential prompt during downloads
3. No new images found

### Missing Troubleshooting Entries

| Scenario | Current Documentation | User Impact (UX assessment) |
|----------|---------------------|----------------------------|
| Gallery blank when opened via `file://` | Undocumented | **High** — The UX review calls this "the most insidious" gap: no visible error, just an empty grid. Every first-time user who double-clicks `index.html` hits this. Should include both a troubleshooting entry AND a `<noscript>` hint in the gallery HTML. |
| Token expiry mid-download (401/403) | Partially covered (generic entry) | **High** — Common during long download sessions. Needs specific guidance on re-running `extract-auth` or refreshing `auth.txt`. |
| macOS Keychain access denied for `extract-auth` | Undocumented | **Medium** — Will become high-frequency once `extract-auth` is documented as the primary auth method. |
| Pillow `UnidentifiedImageError` on corrupt downloads | Undocumented | **Medium** |
| `tagging_config.json` missing API key | Partially covered (error raised, but no troubleshooting entry) | **Medium** |
| `pre-commit` hook blocking commits | Undocumented | **Medium** (contributor-facing) |
| Pyright type errors during `make lint` | Undocumented | **Low** (contributor-facing) |
| `ProcessPoolExecutor` failures on thumbnail generation | Undocumented | **Low** |
| Gallery `metadata.json` corruption or manual editing gone wrong | Mentioned only as a warning ("Avoid editing `metadata.json` manually") | **Medium** |

---

## 7. Skill Files Quality

### Overall Assessment

The 7 skill files represent a **significant investment in AI agent documentation**. They are well-structured with consistent formatting, actionable checklists, and code examples. However, several have **fallen out of sync** with the evolving codebase.

### Per-Skill Analysis

#### `archiver-adr-workflow`
- **Accuracy**: References `docs/adr/` and `docs/adr/README.md` which **do not exist**.
- **Quality**: Template and process are well-defined.
- **Issue**: The skill is premature — no ADR infrastructure has been set up. An agent following this skill would create files in a nonexistent directory.
- **Recommendation**: Either create `docs/adr/README.md` or add a note that the directory must be created first.

#### `archiver-testing-strategy`
- **Accuracy**: Module list matches actual test files. Coverage threshold (85%) matches `Makefile`. Omitted modules list matches `pyproject.toml` `[tool.coverage.run].omit`.
- **Quality**: Excellent fixture examples and mocking guidance.
- **Issue**: The OpenAI mocking example shows `client.chat.completions.create` but the actual code now uses `client.responses.create`. This could lead agents to write incorrect mock setups.
- **Issue**: Test file `test_browser_extract.py` exists but is not listed in the test organization table.
- **Recommendation**: Update the mock example and add `test_browser_extract.py` to the file listing.

#### `credential-handling`
- **Accuracy**: URLs use `chat.openai.com` but actual code uses `chatgpt.com`.
- **Quality**: Thorough security checklist and env var table.
- **Issue**: Missing documentation of the `extract-auth` browser extraction workflow as a credential acquisition method.
- **Recommendation**: Update URLs and add browser extraction section.

#### `gallery-html-patterns`
- **Accuracy**: Architecture description matches the actual implementation.
- **Quality**: Good CSS/JS patterns and accessibility checklist.
- **Issue**: Performance guidelines mention "Thumbnail selection: Grid view loads `small` thumbnails; lightbox loads `large`" — this should be verified against the actual `gallery_index.html` behavior.
- **Recommendation**: Minor — generally accurate and useful.

#### `http-resilience`
- **Accuracy**: The code examples and patterns closely match [http_client.py](src/chatgpt_library_archiver/http_client.py).
- **Quality**: Excellent error categorization table and security notes.
- **Issue**: The retry configuration example shows `backoff_factor=1.0` but the actual default in code is `backoff_factor=0.5`.
- **Recommendation**: Update backoff_factor in the example.

#### `image-pipeline`
- **Accuracy**: Thumbnail sizes match `THUMBNAIL_SIZES` in [thumbnails.py](src/chatgpt_library_archiver/thumbnails.py#L50-L54). Format handling patterns align with actual `_EXT_TO_FORMAT` and `_prepare_for_format`.
- **Quality**: Strong coverage of concurrent processing and error handling.
- **Issue**: The "Reuse images: open the source once, resize from largest to smallest" tip contradicts the actual implementation, which opens the source once and creates independent copies for each size (correct approach).
- **Recommendation**: Minor correction to the performance tip.

#### `openai-vision-api`
- **Accuracy**: **Significantly outdated**. The skill shows `client.chat.completions.create` with `messages` parameter, but the actual code ([ai.py](src/chatgpt_library_archiver/ai.py#L136-L151)) uses `client.responses.create` with `input` parameter and different content type keys (`input_text`/`input_image` vs `text`/`image_url`).
- **Quality**: Configuration resolution chain and telemetry patterns are accurate.
- **Issue**: The API call structure section would cause agents to produce non-functional code if used verbatim.
- **Recommendation**: **High priority** — update the API call examples to match the current `responses.create` interface.

### Skill Files Summary

| Skill | Accuracy | Quality | Priority Fix |
|-------|----------|---------|-------------|
| archiver-adr-workflow | Medium (references nonexistent dir) | High | Low |
| archiver-testing-strategy | Medium (outdated mock pattern) | High | Medium |
| credential-handling | Medium (wrong domain) | High | Medium |
| gallery-html-patterns | High | High | Low |
| http-resilience | High (minor backoff discrepancy) | High | Low |
| image-pipeline | High (minor tip inaccuracy) | High | Low |
| openai-vision-api | **Low** (wrong API interface) | High | **High** |

---

## 8. AGENTS.md Quality

### Current Content

```markdown
# Repository Instructions

- Before committing changes in this repository, run `pre-commit run --all-files`
  and address any issues it reports.
- Install the development dependencies (for example, `pip install -e .[dev]` or
  `make install`).
- Configure Git to use the repository's hooks with `git config core.hooksPath .githooks`.
- The provided Git hook runs `make lint` and `make test`, matching the guidance
  in the README.
```

### Assessment

**Minimal but functional.** The four bullet points cover the essential pre-commit workflow. However, compared to the depth of the skill files and the README, `AGENTS.md` is significantly lighter than expected.

### Missing from AGENTS.md

| Information | Impact |
|-------------|--------|
| Python version requirement (3.10+) | Agent might use wrong Python |
| Project structure overview or pointer to README architecture section | Agent lacks orientation |
| Pointer to skill files | Agent may not discover specialized guidance in `.github/skills/` |
| Coverage threshold (85%) | Agent might not know the bar |
| Ruff rule configuration | Helpful for writing compliant code |
| Testing conventions (fixtures, mocking patterns) | Agent might write non-idiomatic tests |
| Credential files to never commit (`auth.txt`, `tagging_config.json`) | Security risk |

**Recommendation**: Expand `AGENTS.md` to include at least pointers to skill files, Python version, coverage threshold, and the security-sensitive files.

---

## 9. Legal Documentation

### LICENSE

Standard MIT License with copyright holder (Kyle Johnson) and year (2025). Includes an additional non-affiliation clause. **Adequate**.

### DISCLAIMER.md

Clear, concise disclaimer covering:
- Non-affiliation with OpenAI
- Terms of Service compliance responsibility
- No liability for misuse

**Adequate** for an open-source personal archival tool. Consider adding a note about image copyright (users don't necessarily own copyright to AI-generated images depending on jurisdiction and ToS).

---

## 10. Getting Started Experience

### Step-by-Step Assessment

| Step | Documentation | Friction Points |
|------|--------------|-----------------|
| Install Python 3.10+ | Mentioned as prerequisite | No installation guidance (reasonable to omit) |
| Clone repository | Not documented | Standard for GitHub projects |
| Setup virtual environment | Options A and B documented | Clear |
| Install dependencies | Multiple methods documented | Perhaps too many options for a beginner |
| Get auth credentials | Detailed browser instructions | 7-step process could benefit from screenshots |
| First download run | `python -m chatgpt_library_archiver` | Simple |
| View gallery | Not explicitly documented | Users must know to open `gallery/index.html` in a browser |
| Tag images | Documented with examples | Requires separate `tagging_config.json` setup |

### Critical Missing Step

**How to view the gallery**: After running the download, the README never explicitly says "open `gallery/index.html` in your browser" as a discrete step. The gallery viewer is described in the Notes section, but the "happy path" workflow doesn't include this step.

The UX cross-review adds important context: the `gallery/` directory contains both `index.html` and legacy `page_*.html` files, so new users might open the wrong one. Additionally, `file://` protocol doesn't reliably load `metadata.json` via `fetch()` — users need to serve the gallery via HTTP. The recommended post-download instruction should be:

```
cd gallery && python -m http.server 8000
# Then open http://localhost:8000/
```

### Browser Credential Extraction — Highest-Impact Documentation Change

The `extract-auth` command would dramatically simplify the getting-started experience, but it is **completely undocumented** in the README.

The UX cross-review makes a compelling case that this is **the single highest-impact documentation fix in the entire project**, not merely a High-priority gap. The reasoning:

| Auth Method | Steps | Error-Prone? | User Skill Required |
|-------------|-------|-------------|--------------------|
| Manual (documented) | 7+ (open DevTools → Network tab → find request → copy 7+ headers → paste into file) | Yes — wrong header, missed semicolon, stale copy | Moderate (DevTools familiarity) |
| `extract-auth` (undocumented) | 1 (`chatgpt-archiver extract-auth --browser edge`) | No — automated extraction | None |

Most CLI tool abandonment occurs during initial setup. Reducing auth from "follow 7 instructions and maybe copy the wrong header" to "run one command" directly affects user retention. This should be documented as the **primary** auth method for macOS users, with manual extraction as a fallback.

---

## 11. API/Developer Documentation

### For Contributors

- `CONTRIBUTING` section exists in README (brief — "open an issue or submit a PR")
- Testing section provides detailed guidance on test organization, running tests, and extending the suite
- Architecture overview serves as a module guide
- Skill files provide deep domain knowledge

### Missing

- **No API documentation**: For someone wanting to use `chatgpt_library_archiver` as a library (importing modules), there's no API reference. The `pyproject.toml` registers a console script entry point (`chatgpt-archiver`), but programmatic usage isn't documented.
- **No developer setup beyond testing**: The README covers running tests but not debugging, IDE setup, or development workflow.
- **No issue/PR templates**: Standard GitHub project infrastructure that helps standardize contributions.

---

## 12. Documentation Gaps — What's Missing Entirely

| Gap | Impact | Priority |
|-----|--------|----------|
| `extract-auth` command documentation | Users miss an easier auth workflow | High |
| `--browser` download flag documentation | Feature completely invisible | High |
| ADR directory and initial records | Skill file references nonexistent infrastructure | Medium |
| "How to view the gallery" explicit step | New users don't know what to do after download | Medium |
| `ARCHIVER_ASSUME_YES` env var in README | CI/scripted usage lacks guidance | Medium |
| API reference for programmatic usage | Library consumers have no guide | Medium |
| Gallery viewer keyboard shortcuts summary | Buried in prose, no quick-reference | Low |
| Supported image formats list | Users don't know what file types work | Low |
| Version history / CHANGELOG | No way to track what changed | Low |
| `browser_extract.py` in Architecture Overview | 509-line module invisible in architecture docs | Low |

---

## 13. Good Documentation Examples

These sections serve as models for the project's documentation standards:

1. **README Architecture Overview** (lines 242–310): Clear module descriptions with explicit responsibility boundaries. The `metadata.json` field documentation is particularly thorough.

2. **`browser_extract.py` module docstring**: Multi-line, explains mechanism and dependencies — ideal for complex modules.

3. **`http_client.py` method docstrings**: `stream_download` documents parameters, validation behavior, and error conditions concisely.

4. **`thumbnails.py` `thumbnail_relative_path`**: NumPy-style `Parameters` section for a function with non-obvious semantics.

5. **Skill files structure**: Consistent format with "When to use", code examples, tables, and checklists. The `http-resilience` error categorization table is especially useful.

---

## 14. Prioritized Recommendations

*Updated with input from UX and synthesis cross-reviews. Changes from the original assessment are noted inline.*

### P0 — Fix Now (Accuracy Errors and Security)

1. **Fix `httpx` → `requests` in README** line 259. One-word change with high impact — anyone reading the architecture section is learning the wrong HTTP library.

2. **Reconcile domain names**: Update README `auth.txt` example, prerequisites, and instructions from `chat.openai.com` to `chatgpt.com` to match `auth.txt.example` and the actual code. Update the credential-handling skill file similarly.

3. **Remove/replace the API key value in `tagging_config.json`** in the working tree. *(Elevated from P3 → P0 per synthesis: even though `.gitignore` prevents commits, the file sets a bad example and the key may still be live. The synthesis correctly identifies this as a Critical security item.)*

4. **Document `extract-auth` command** as the primary macOS auth method in README. Include `--browser`, `--output`, `--dry-run`, `--no-verify` flags. *(Elevated from P1 → P0 per UX review: this is the single highest-impact change for new user retention — transforms a fragile 7-step manual process into one command.)*

### P1 — Fix Soon (Missing Features, Security-Preventing Documentation)

5. **Document `--browser` flag** on the `download` command in README.

6. **Add explicit "View your gallery" step** to the README workflow, including HTTP serving instructions (`python -m http.server 8000`). *(Elevated from P2 per UX review: this is the payoff moment of the entire tool, and it's undocumented. The `file://` protocol issue makes the serving instructions non-optional.)*

7. **Update `openai-vision-api` skill**: Replace `chat.completions.create` examples with `responses.create` and update content type keys.

8. **Update `archiver-testing-strategy` skill**: Fix OpenAI mock example to use `responses.create`.

9. **Add warning about not publicly hosting `metadata.json`** in README gallery section. *(New — from security-preventing documentation analysis: contains signed download URLs and internal file IDs.)*

10. **Add troubleshooting entry for gallery blank over `file://`** — the UX review identifies this as the highest-frequency troubleshooting gap, affecting every first-time user who double-clicks `index.html`. *(Elevated from unlisted → P1.)*

### P2 — Improve (Quality Enhancements)

11. **Add module docstring to `utils.py`** and `gallery.py`.

12. **Expand `AGENTS.md`** with Python version (3.10+), pointer to skill files, coverage threshold (85%), and security-sensitive files list (`auth.txt`, `tagging_config.json`).

13. **Add `test_browser_extract.py`** to the testing strategy skill's file listing.

14. **Create `docs/adr/README.md`** to match the ADR skill's assumptions, or update the skill to note the directory must be created.

15. **Document `ARCHIVER_ASSUME_YES`** environment variable in README for CI/scripted use.

16. **Document gallery keyboard shortcuts and boolean search syntax** prominently — not just buried in prose. The UX review argues these are more impactful than originally rated (Low → Medium) because boolean search across 1 169 images is a key differentiating feature that is completely undiscoverable without documentation. *(Elevated from P3-level.)*

17. **Add privacy/consent documentation for the `tag` command**. *(New — UX review: images are sent to OpenAI's vision API without notification; at minimum document this, ideally add a consent prompt.)*

### P3 — Nice to Have

18. Add macOS Keychain troubleshooting entry for `extract-auth`.
19. Add supported image formats list to README.
20. Standardize docstring style (choose between Google-style Args/Returns and NumPy-style Parameters).
21. Consider adding a CHANGELOG.md for version tracking.
22. Create `tagging_config.json.example` (analogous to `auth.txt.example`).
23. Document minimum required API key permissions/scopes for both ChatGPT Bearer token and OpenAI API key.

---

## 15. Security-Preventing Documentation Gaps

*New section — incorporated from the documentation synthesis which identified 12 documentation items that, if they existed, would prevent users from making dangerous misconfigurations.*

Not all documentation gaps are equal. Some are convenience issues; others directly prevent security incidents. The most impactful security-preventing documentation items not already covered in §14:

| Documentation Gap | Security Risk It Prevents | Priority |
|-------------------|--------------------------|----------|
| Document that `tagging_config.json` should have `600` permissions | World-readable API keys on shared systems | P1 (code fix preferred, but document until then) |
| Warn against publicly hosting `metadata.json` | Exposes signed download URLs and internal file IDs | **P1 — in §14** |
| Document API key rotation procedure + link to OpenAI key management | Users who leak keys don't know how to recover | P2 |
| Document that Bearer tokens have broad scopes (including `organization.write`) | Users underestimate blast radius of a token leak | P2 |
| Note that credentials follow HTTP redirects (until code fix lands) | Token leakage through proxies or corporate networks | P2 |
| Note that `input()` echoes API keys to terminal | Exposure in shared sessions (tmux, pair programming) | P3 |

The synthesis's framing is useful: when prioritizing documentation work, items that prevent security misconfigurations should be weighted above pure convenience gaps of the same estimated effort.

---

## 16. Cross-Review Assessment

### Findings Incorporated

The cross-reviews surfaced several genuinely valuable insights that improved this review:

- **`extract-auth` priority elevation** (UX review): The 7-step-vs-1-command comparison and user-retention argument are compelling. Elevated to P0.
- **`tagging_config.json` API key priority elevation** (synthesis): Correctly identified as Critical — a live key in the working tree is worse than a documentation gap. Elevated to P0.
- **`file://` protocol troubleshooting** (UX review): A real gap this review missed entirely. First-time users who double-click `index.html` see a blank page with no error.
- **Security-preventing documentation framing** (synthesis): A productive way to prioritize documentation work that this review didn't apply.
- **Privacy consent for `tag` command** (UX review): Legitimate concern — sending user images to a third-party API without notification warrants at minimum documentation, ideally a prompt.
- **Gallery search discoverability** (UX review): Boolean search (AND/OR/NOT/parentheses) is a differentiating feature that's completely hidden.

### Findings Noted as Overstated or Imprecise

- **The "63 gaps" count** (synthesis): While accurate, the number overstates urgency. Many items are Low severity and typical for a v0.1.0 project (no CHANGELOG, no issue templates, no PR templates, no contributing guide, no API reference). These are aspirational, not gaps.
- **Missing "data flow diagram" and "module dependency diagram"** (synthesis D-5, D-6): Rated Medium, but for a project of this size (~14 modules) the README Architecture Overview already provides sufficient orientation. Diagrams become cost-effective at larger scales.
- **Docstring style inconsistency** (synthesis E-5): Flagged in both reviews, but the actual inconsistency is one module (`thumbnails.py`) using NumPy-style while the rest use Google-style. This is a minor nit, not a meaningful consistency issue.
- **`file://` link allowlist in `safeHref()`** (UX review §2.3): The UX review proposes adding `file:` to the URL scheme allowlist. While technically safe (no script injection), this gives `file://` a more "supported" status than warranted. The better approach is the UX review's own §4.2 recommendation: accept `file://` as a degraded experience and steer users to HTTP serving.

---

## Methodology

This review was conducted by reading:
- All top-level documentation files (`README.md`, `AGENTS.md`, `DISCLAIMER.md`, `LICENSE`)
- Project configuration (`pyproject.toml`, `Makefile`, `auth.txt.example`, `tagging_config.json`)
- All 7 skill files in `.github/skills/*/SKILL.md`
- Source modules: `ai.py`, `http_client.py`, `incremental_downloader.py`, `gallery.py`, `thumbnails.py`, `metadata.py`, `status.py`, `utils.py`, `browser_extract.py`, `__init__.py`, `__main__.py`
- CLI wiring: `cli/app.py`, `cli/commands/download.py`, `cli/commands/extract_auth.py`
- `.gitignore` for credential file verification

Cross-references were verified by searching for keywords (`httpx`, `chat.openai.com`, `chatgpt.com`, `extract-auth`) across the entire codebase.

The cross-review update incorporated findings from:
- `docs/reviews/cross-review-ux-perspective.md` — UX impact assessment of security and documentation findings
- `docs/reviews/cross-review-documentation-synthesis.md` — Comprehensive synthesis of 63 deduplicated gaps across all 9 review reports

---

## Cross-Review Contributors

| Contributor | Perspective | Key Contributions |
|-------------|-------------|-------------------|
| Gallery UX Designer | UX impact assessment (`cross-review-ux-perspective.md`) | Elevated `extract-auth` to highest-impact fix; identified `file://` protocol as insidious troubleshooting gap; proposed privacy consent for `tag` command; provided unified solutions for security×UX conflicts |
| Documentation Specialist | Comprehensive synthesis (`cross-review-documentation-synthesis.md`) | Deduplicated 63 gaps across 9 reviews into 6 categories; identified 12 security-preventing documentation items; elevated `tagging_config.json` API key to Critical; provided cross-reference index for traceability |
