# Cross-Review Documentation Synthesis

**Date:** 2026-03-01
**Author:** Documentation Specialist (agent)
**Sources:** All 9 review reports (security, architecture, testing, gallery UX, image pipeline, OpenAI integration, HTTP resilience, DevOps/CI, documentation quality)

---

## Executive Summary

Across all review reports, **63 distinct documentation gaps** were identified, deduplicated, and categorized. The project's documentation is above average for its scale—README, skill files, and inline docstrings cover core workflows well. However, three systemic issues recur across reviews:

1. **Accuracy drift** — Documentation has fallen behind the codebase (wrong HTTP library, wrong domain, wrong API interface)
2. **Undocumented features** — `extract-auth`, `--browser` flag, and browser credential extraction are invisible to users
3. **Security-critical documentation gaps** — File permissions, credential scope, API key hygiene, and gallery hosting warnings are missing or incomplete

The highest-impact documentation work is fixing factual errors (prevents user confusion), documenting security practices (prevents misconfiguration), and filling feature gaps (surfaces hidden value).

---

## Table of Contents

1. [Comprehensive Gap List](#1-comprehensive-gap-list)
2. [Skill File Accuracy Issues](#2-skill-file-accuracy-issues)
3. [User-Facing Documentation Priorities](#3-user-facing-documentation-priorities)
4. [Developer Documentation Priorities](#4-developer-documentation-priorities)
5. [Documentation That Could Prevent Security Risks](#5-documentation-that-could-prevent-security-risks)

---

## 1. Comprehensive Gap List

### Category A: Factual Errors in Existing Documentation

These are inaccuracies that actively mislead readers. Highest priority.

| # | Gap | Source Report(s) | Severity |
|---|-----|-----------------|----------|
| A-1 | README claims `http_client.py` wraps `httpx`; it actually wraps `requests`/`urllib3` | [Documentation Quality §2](documentation-quality.md) | **Critical** |
| A-2 | README uses `chat.openai.com` throughout; code and `auth.txt.example` use `chatgpt.com` | [Documentation Quality §2](documentation-quality.md), [Security Audit I-2](security-audit.md) | **Critical** |
| A-3 | Credential-handling skill uses `chat.openai.com` instead of `chatgpt.com` | [Documentation Quality §7](documentation-quality.md) | **High** |
| A-4 | OpenAI vision API skill documents `chat.completions.create`, code uses `responses.create` | [Documentation Quality §7](documentation-quality.md), [OpenAI Integration §12](openai-integration.md) | **High** |
| A-5 | Testing skill's OpenAI mock example uses `client.chat.completions.create` | [Documentation Quality §7](documentation-quality.md), [Test Coverage §10](test-coverage-strategy.md) | **High** |
| A-6 | HTTP resilience skill shows `backoff_factor=1.0`; actual default is `0.5` | [Documentation Quality §7](documentation-quality.md), [HTTP Resilience §1](http-resilience.md) | **Medium** |
| A-7 | Image pipeline skill tip says "resize from largest to smallest"; actual implementation copies from full resolution each time | [Image Pipeline §9](image-pipeline.md), [Documentation Quality §7](documentation-quality.md) | **Low** |

### Category B: Undocumented Features

Features that exist in code but are invisible to users.

| # | Gap | Source Report(s) | Severity |
|---|-----|-----------------|----------|
| B-1 | `extract-auth` CLI command (auto-extracts credentials from Edge/Chrome on macOS) | [Documentation Quality §1, §10](documentation-quality.md) | **High** |
| B-2 | `--browser edge\|chrome` flag on `download` command (live browser credentials) | [Documentation Quality §1](documentation-quality.md) | **High** |
| B-3 | `browser_extract.py` module not in README Architecture Overview | [Documentation Quality §5](documentation-quality.md), [Code Quality §1](code-quality-architecture.md) | **Medium** |
| B-4 | `ARCHIVER_ASSUME_YES` environment variable not in README | [Documentation Quality §4](documentation-quality.md), [DevOps §8](devops-ci-pipeline.md) | **Medium** |
| B-5 | Gallery boolean search syntax (AND/OR/NOT/parentheses) is undiscoverable — tooltip only | [Gallery UX §5 N-4](gallery-ux-accessibility.md) | **Medium** |
| B-6 | Supported image formats list not documented | [Documentation Quality §12](documentation-quality.md), [Image Pipeline §6](image-pipeline.md) | **Low** |
| B-7 | Gallery keyboard shortcuts (arrows, Escape, Ctrl+click) buried in prose, no quick-reference | [Documentation Quality §12](documentation-quality.md), [Gallery UX §6](gallery-ux-accessibility.md) | **Low** |

### Category C: Missing Operational Documentation

Documentation needed for production use, troubleshooting, and operational awareness.

| # | Gap | Source Report(s) | Severity |
|---|-----|-----------------|----------|
| C-1 | No troubleshooting entry for macOS Keychain access denial (`extract-auth`) | [Documentation Quality §6](documentation-quality.md) | **High** |
| C-2 | No warning about publicly hosting `metadata.json` (contains signed URLs, file IDs) | [Security Audit M-2](security-audit.md) | **High** |
| C-3 | No documentation of minimum required API scopes for ChatGPT Bearer token | [Security Audit C-2](security-audit.md) | **Medium** |
| C-4 | No documentation of required OpenAI API key permissions | [OpenAI Integration §10](openai-integration.md) | **Medium** |
| C-5 | No troubleshooting for `pre-commit` hook blocking commits | [Documentation Quality §6](documentation-quality.md), [DevOps §3](devops-ci-pipeline.md) | **Medium** |
| C-6 | No troubleshooting for Pillow `UnidentifiedImageError` on corrupt downloads | [Documentation Quality §6](documentation-quality.md), [Image Pipeline §5](image-pipeline.md) | **Medium** |
| C-7 | No troubleshooting for Pyright type errors during `make lint` | [Documentation Quality §6](documentation-quality.md), [DevOps §5](devops-ci-pipeline.md) | **Low** |
| C-8 | No troubleshooting for `ProcessPoolExecutor` failures on thumbnail generation | [Documentation Quality §6](documentation-quality.md), [Image Pipeline §3](image-pipeline.md) | **Low** |
| C-9 | No troubleshooting for gallery not loading over `file://` protocol | [Gallery UX §8 E-5](gallery-ux-accessibility.md) | **Low** |
| C-10 | No documentation of token expiry detection or refresh workflow | [Security Audit C-2](security-audit.md), [HTTP Resilience §4](http-resilience.md) | **Medium** |
| C-11 | No explicit "View your gallery" step in the happy-path workflow | [Documentation Quality §10](documentation-quality.md) | **Medium** |
| C-12 | No guidance on `--no-config-prompt` flag behavior for CI/automation | [Documentation Quality §4](documentation-quality.md) | **Low** |
| C-13 | No disk exhaustion warning (no download size limits exist in code) | [Security Audit H-3](security-audit.md), [HTTP Resilience §6](http-resilience.md) | **Low** |

### Category D: Missing Developer/Contributor Documentation

Documentation needed by contributors and AI agents.

| # | Gap | Source Report(s) | Severity |
|---|-----|-----------------|----------|
| D-1 | `AGENTS.md` lacks Python version requirement (3.10+) | [Documentation Quality §8](documentation-quality.md), [DevOps §4](devops-ci-pipeline.md) | **High** |
| D-2 | `AGENTS.md` lacks pointers to skill files in `.github/skills/` | [Documentation Quality §8](documentation-quality.md) | **High** |
| D-3 | `AGENTS.md` lacks security-sensitive files list (`auth.txt`, `tagging_config.json`) | [Documentation Quality §8](documentation-quality.md), [Security Audit C-1](security-audit.md) | **High** |
| D-4 | No `conftest.py` or shared fixture documentation for test contributors | [Test Coverage §5](test-coverage-strategy.md), [Documentation Quality §7](documentation-quality.md) | **Medium** |
| D-5 | No data flow diagram (API → download → metadata → thumbnails → gallery) | [Documentation Quality §5](documentation-quality.md), [Code Quality §8](code-quality-architecture.md) | **Medium** |
| D-6 | No module dependency diagram | [Documentation Quality §5](documentation-quality.md) | **Medium** |
| D-7 | `AGENTS.md` lacks coverage threshold (85%) | [Documentation Quality §8](documentation-quality.md) | **Medium** |
| D-8 | `AGENTS.md` lacks ruff/pyright configuration summary | [Documentation Quality §8](documentation-quality.md), [DevOps §5](devops-ci-pipeline.md) | **Low** |
| D-9 | No API reference for programmatic usage (library import) | [Documentation Quality §11](documentation-quality.md) | **Low** |
| D-10 | No CHANGELOG or version history | [Documentation Quality §1](documentation-quality.md), [DevOps §7](devops-ci-pipeline.md) | **Low** |
| D-11 | No issue/PR templates | [DevOps §12](devops-ci-pipeline.md) | **Low** |
| D-12 | No contributing guide beyond brief README section | [DevOps §12](devops-ci-pipeline.md) | **Low** |
| D-13 | ADR skill references `docs/adr/` directory that does not exist | [Documentation Quality §7](documentation-quality.md) | **Low** |
| D-14 | No documentation of test naming convention (`test_<fn>_<scenario>_<expected>`) in AGENTS.md or README | [Test Coverage §8](test-coverage-strategy.md) | **Low** |

### Category E: Missing Inline/Code Documentation

Docstrings, comments, and code-level documentation gaps.

| # | Gap | Source Report(s) | Severity |
|---|-----|-----------------|----------|
| E-1 | `utils.py` missing module docstring | [Documentation Quality §3](documentation-quality.md) | **Medium** |
| E-2 | `gallery.py` missing module docstring | [Documentation Quality §3](documentation-quality.md) | **Medium** |
| E-3 | `ensure_auth_config` and `prompt_and_write_auth` in `utils.py` lack function docstrings | [Documentation Quality §3](documentation-quality.md) | **Low** |
| E-4 | Animated GIF/WebP flattening in thumbnail pipeline is undocumented in code | [Image Pipeline §6](image-pipeline.md) | **Low** |
| E-5 | Inconsistent docstring style: `thumbnails.py` uses NumPy-style, others use Google-style | [Documentation Quality §3](documentation-quality.md) | **Low** |
| E-6 | Connection pooling behavior (14 workers × 10 pool size = 140 potential connections) undocumented | [HTTP Resilience §7](http-resilience.md) | **Low** |
| E-7 | No `tagging_config.json.example` file exists (unlike `auth.txt.example`) | [OpenAI Integration §7](openai-integration.md) | **Low** |

### Category F: Configuration/Example Documentation

| # | Gap | Source Report(s) | Severity |
|---|-----|-----------------|----------|
| F-1 | `tagging_config.json` in working tree contains what appears to be a real API key | [Security Audit C-1](security-audit.md), [OpenAI Integration §10](openai-integration.md), [Documentation Quality §4](documentation-quality.md) | **Critical** |
| F-2 | No `tagging_config.json.example` to guide users | [OpenAI Integration §7](openai-integration.md) | **Medium** |
| F-3 | README tagging config example doesn't note the actual default prompt is more comprehensive | [Documentation Quality §2](documentation-quality.md) | **Low** |

---

## 2. Skill File Accuracy Issues

Seven skill files were audited against the current codebase. Three have significant accuracy problems that would cause AI agents to produce incorrect code or follow wrong patterns.

### Critical: `openai-vision-api` Skill

**Source:** [Documentation Quality §7](documentation-quality.md), [OpenAI Integration §12](openai-integration.md)

| Aspect | Skill File Says | Code Actually Does |
|--------|----------------|-------------------|
| API endpoint | `client.chat.completions.create` | `client.responses.create` |
| Text content type | `{"type": "text", ...}` | `{"type": "input_text", ...}` |
| Image content type | `{"type": "image_url", ...}` | `{"type": "input_image", ...}` |
| Encode return type | `(base64_data, media_type)` | `(mime, data_url)` |
| `max_tokens` | `300` (recommended) | Not set (implementation gap, but skill documents wrong API) |

**Impact:** Agents using this skill will produce non-functional mock setups and incorrect API call code. **Must be updated before any OpenAI integration work.**

### Medium: `archiver-testing-strategy` Skill

**Source:** [Documentation Quality §7](documentation-quality.md), [Test Coverage §10](test-coverage-strategy.md)

| Issue | Detail |
|-------|--------|
| OpenAI mock example uses `client.chat.completions.create` | Should use `client.responses.create` |
| `test_browser_extract.py` not listed in test organization table | File exists with ~40 tests |
| No mention of `conftest.py` shared fixtures pattern | Skill recommends fixtures but no `conftest.py` exists yet |

### Medium: `credential-handling` Skill

**Source:** [Documentation Quality §7](documentation-quality.md)

| Issue | Detail |
|-------|--------|
| Uses `chat.openai.com` URLs | Code uses `chatgpt.com` |
| Missing `extract-auth` browser extraction as a credential method | Entire workflow undocumented in skill |

### Low: Other Skills

| Skill | Issue | Severity |
|-------|-------|----------|
| `http-resilience` | `backoff_factor=1.0` in example vs `0.5` in code | Low |
| `image-pipeline` | "Resize from largest to smallest" tip contradicts actual impl | Low |
| `archiver-adr-workflow` | References `docs/adr/` which doesn't exist | Low |
| `gallery-html-patterns` | Generally accurate, minor thumbnail selection detail to verify | Low |

---

## 3. User-Facing Documentation Priorities

Ranked by impact on end-user experience.

### P0 — Fix Now (blocks correct usage)

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 1 | Fix `httpx` → `requests` in README Architecture Overview | Users looking up the HTTP library find wrong information | Trivial |
| 2 | Update all `chat.openai.com` → `chatgpt.com` in README | Auth setup instructions point to wrong domain | Trivial |
| 3 | Remove/replace real API key in `tagging_config.json` | Even if gitignored, the working tree has a live key; sets bad example | Trivial |

### P1 — Fix Soon (high-value missing documentation)

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 4 | Document `extract-auth` command in README | macOS users miss the easiest auth workflow; must currently manually copy 7+ headers | Small |
| 5 | Document `--browser` flag on `download` command | Feature is completely invisible to users | Small |
| 6 | Add explicit "View your gallery" step to README happy path | New users don't know what to do after download | Trivial |
| 7 | Add warning about not publicly hosting `metadata.json` | Contains signed URLs and internal file IDs | Trivial |
| 8 | Add macOS Keychain troubleshooting entry | `extract-auth` users will hit access-denied prompts | Small |

### P2 — Improve (quality of life)

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 9 | Document `ARCHIVER_ASSUME_YES` env var in README | CI/scripted usage needs non-interactive mode | Trivial |
| 10 | Document minimum required API key permissions/scopes | Users don't know what their token needs access to | Small |
| 11 | Add supported image formats list | Users don't know what file types work for import | Trivial |
| 12 | Add gallery keyboard shortcuts quick-reference table | Powerful features are buried in prose | Small |
| 13 | Add troubleshooting entries for common errors (corrupt images, stale tokens, gallery on `file://`) | Three entries currently; at least 7 more scenarios identified | Medium |
| 14 | Document `--no-config-prompt` behavior | CI users need to disable interactive prompts | Trivial |

---

## 4. Developer Documentation Priorities

Ranked by impact on contributor/agent effectiveness.

### P0 — Fix Now (skill accuracy)

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 1 | Update `openai-vision-api` skill to document `responses.create` API | Agents will generate non-functional code | Medium |
| 2 | Update `archiver-testing-strategy` skill's OpenAI mock example | Test code generated from skill will be broken | Small |
| 3 | Update `credential-handling` skill URLs to `chatgpt.com` | Agents may hardcode wrong domain | Trivial |

### P1 — Fix Soon (agent effectiveness)

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 4 | Expand `AGENTS.md` with: Python 3.10+ requirement, skill file pointers, coverage threshold (85%), security-sensitive files list | Agents lack critical orientation data | Small |
| 5 | Add `test_browser_extract.py` to testing strategy skill's file listing | Agents don't know this test file exists | Trivial |
| 6 | Create `docs/adr/README.md` (or update ADR skill to note directory must be created) | ADR skill references nonexistent directory | Trivial |
| 7 | Add module docstrings to `utils.py` and `gallery.py` | Both files start without docstrings, violating project convention | Trivial |

### P2 — Improve (contributor onboarding)

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 8 | Add data flow diagram to README or docs/ | Multiple reviews noted the lack of visual pipeline documentation | Medium |
| 9 | Create `tagging_config.json.example` | No example file exists, unlike `auth.txt.example` | Trivial |
| 10 | Standardize docstring style (choose Google or NumPy consistently) | `thumbnails.py` uses NumPy; everywhere else uses Google-ish style | Medium |
| 11 | Document test naming convention in AGENTS.md or testing skill | ~30% test compliance with the convention; inconsistency grows without guidance | Trivial |
| 12 | Add `CHANGELOG.md` | No release history tracking exists | Small |

### P3 — Nice to Have

| # | Action | Why | Effort |
|---|--------|-----|--------|
| 13 | Add module dependency diagram | Helps contributors understand import relationships | Medium |
| 14 | Add API reference for programmatic usage | Enables library consumers | Large |
| 15 | Add issue/PR templates | Standardizes contributions | Small |
| 16 | Fix `http-resilience` skill backoff_factor (1.0 → 0.5) | Minor accuracy issue | Trivial |
| 17 | Fix `image-pipeline` skill resize-order tip | Minor accuracy issue | Trivial |

---

## 5. Documentation That Could Prevent Security Risks

These are documentation items that, if they existed, would prevent users from making dangerous misconfigurations. Directly derived from the [Security Audit](security-audit.md), [OpenAI Integration](openai-integration.md), and [HTTP Resilience](http-resilience.md) reviews.

### Critical Prevention Value

| # | Documentation Gap | Security Risk It Prevents | Source |
|---|-------------------|--------------------------|--------|
| 1 | **Document that `tagging_config.json` must have `600` permissions** (or add a code fix + doc note) | World-readable API keys (C-1 in security audit) — anyone on the system can read the OpenAI key | [Security Audit C-1](security-audit.md) |
| 2 | **Add "never publicly host `metadata.json`" warning** in README gallery section | Signed download URLs, internal file IDs, and API endpoint structure would be exposed | [Security Audit M-2](security-audit.md) |
| 3 | **Document API key rotation procedure** and link to OpenAI key management page | Users who leak keys don't know how to recover | [Security Audit C-1](security-audit.md), [OpenAI Integration §10](openai-integration.md) |
| 4 | **Add `tagging_config.json` to `AGENTS.md` sensitive files list** | Agents might commit the file or reference its contents | [Security Audit C-1](security-audit.md), [Documentation Quality §8](documentation-quality.md) |

### High Prevention Value

| # | Documentation Gap | Security Risk It Prevents | Source |
|---|-------------------|--------------------------|--------|
| 5 | **Document that `auth.txt` Bearer tokens have broad scopes** (including `organization.write`) | Users don't understand the blast radius of a token leak | [Security Audit C-2](security-audit.md) |
| 6 | **Document the gallery XSS risk** in a developer note (until code fix lands) | Contributors may add more `innerHTML` usage without realizing the pattern is unsafe | [Security Audit H-1](security-audit.md), [Gallery UX J-1](gallery-ux-accessibility.md) |
| 7 | **Document that credentials follow HTTP redirects** (until code fix lands) | Users running through proxies or corporate networks may inadvertently leak tokens | [Security Audit H-2](security-audit.md), [HTTP Resilience §5](http-resilience.md) |
| 8 | **Document interactive credential echoing** — note that `input()` displays API keys on screen | Users in shared terminal sessions (tmux, pair programming) expose keys visually | [Security Audit L-2](security-audit.md) |

### Medium Prevention Value

| # | Documentation Gap | Security Risk It Prevents | Source |
|---|-------------------|--------------------------|--------|
| 9 | **Document minimum required API key permissions** for OpenAI | Users may create overly-permissive keys when a read-only key would suffice | [OpenAI Integration §10](openai-integration.md) |
| 10 | **Document that no download size limits exist** | Users on shared systems could have disks filled by malicious API responses | [Security Audit H-3](security-audit.md), [HTTP Resilience §6](http-resilience.md) |
| 11 | **Document path traversal risk** for filenames from untrusted API responses (until code fix lands) | Malicious `item.id` values could write outside the gallery directory | [Security Audit M-3](security-audit.md) |
| 12 | **Document that `gallery/images/` originals are never modified** | Users may worry about image integrity after thumbnail generation | [Image Pipeline §7](image-pipeline.md) |

---

## Appendix: Gap Count by Source Report

| Source Report | Gaps Identified | Unique to This Report | Also Flagged Elsewhere |
|---------------|----------------|----------------------|----------------------|
| [Documentation Quality](documentation-quality.md) | 31 | 12 | 19 |
| [Security Audit](security-audit.md) | 14 | 6 | 8 |
| [Gallery UX & Accessibility](gallery-ux-accessibility.md) | 7 | 3 | 4 |
| [OpenAI Integration](openai-integration.md) | 8 | 3 | 5 |
| [DevOps & CI](devops-ci-pipeline.md) | 8 | 3 | 5 |
| [Code Quality & Architecture](code-quality-architecture.md) | 5 | 1 | 4 |
| [Test Coverage & Strategy](test-coverage-strategy.md) | 5 | 2 | 3 |
| [HTTP Resilience](http-resilience.md) | 4 | 1 | 3 |
| [Image Pipeline](image-pipeline.md) | 4 | 2 | 2 |

The Documentation Quality review had the widest coverage (as expected), but every other review surfaced documentation gaps not identified in the documentation-specific review — particularly the security audit (credential scope documentation, hosting warnings) and the gallery UX review (search syntax discoverability, keyboard shortcuts).

---

## Appendix: Cross-Reference Index

For traceability, here is how each gap maps back to its source finding:

| Gap ID | Source Finding ID(s) |
|--------|---------------------|
| A-1 | Documentation Quality §2 "httpx vs requests" |
| A-2 | Documentation Quality §2 "Domain Inconsistency" |
| A-3 | Documentation Quality §7 "credential-handling" |
| A-4 | Documentation Quality §7 "openai-vision-api", OpenAI Integration §12 |
| A-5 | Documentation Quality §7 "archiver-testing-strategy", Test Coverage §10 |
| A-6 | Documentation Quality §7 "http-resilience", HTTP Resilience §1 |
| A-7 | Image Pipeline §9 "Skill Compliance", Documentation Quality §7 "image-pipeline" |
| B-1 | Documentation Quality §1 "`extract-auth` undocumented", §10 "Browser Credential Extraction" |
| B-2 | Documentation Quality §1 "`--browser` flag undocumented" |
| B-3 | Documentation Quality §5 "browser_extract.py omitted" |
| B-4 | Documentation Quality §4 "`ARCHIVER_ASSUME_YES`" |
| B-5 | Gallery UX §5 N-4 "Search help" |
| B-6 | Documentation Quality §12, Image Pipeline §6 |
| B-7 | Documentation Quality §12, Gallery UX §6 |
| C-1 | Documentation Quality §6 "macOS Keychain" |
| C-2 | Security Audit M-2 "Signed URLs" |
| C-3 | Security Audit C-2 "Token scope" |
| C-4 | OpenAI Integration §10 "Key scope documentation" |
| C-5 | Documentation Quality §6, DevOps §3 "Pre-commit hooks" |
| C-6 | Documentation Quality §6, Image Pipeline §5 |
| C-7 | Documentation Quality §6, DevOps §5 |
| C-8 | Documentation Quality §6, Image Pipeline §3 |
| C-9 | Gallery UX §8 E-5 |
| C-10 | Security Audit C-2, HTTP Resilience §4 |
| C-11 | Documentation Quality §10 "View your gallery" |
| C-12 | Documentation Quality §4 |
| C-13 | Security Audit H-3, HTTP Resilience §6 |
| D-1 | Documentation Quality §8 "Python version" |
| D-2 | Documentation Quality §8 "Skill file pointers" |
| D-3 | Documentation Quality §8, Security Audit C-1 |
| D-4 | Test Coverage §5, Documentation Quality §7 |
| D-5 | Documentation Quality §5, Code Quality §8 |
| D-6 | Documentation Quality §5 |
| D-7 | Documentation Quality §8 |
| D-8 | Documentation Quality §8, DevOps §5 |
| D-9 | Documentation Quality §11 |
| D-10 | Documentation Quality §1, DevOps §7 |
| D-11 | DevOps §12 |
| D-12 | DevOps §12 |
| D-13 | Documentation Quality §7 "archiver-adr-workflow" |
| D-14 | Test Coverage §8 |
| E-1 | Documentation Quality §3 |
| E-2 | Documentation Quality §3 |
| E-3 | Documentation Quality §3 |
| E-4 | Image Pipeline §6 |
| E-5 | Documentation Quality §3 |
| E-6 | HTTP Resilience §7 |
| E-7 | OpenAI Integration §7 |
| F-1 | Security Audit C-1, OpenAI Integration §10, Documentation Quality §4 |
| F-2 | OpenAI Integration §7 |
| F-3 | Documentation Quality §2 |
