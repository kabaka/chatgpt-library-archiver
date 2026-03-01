# OpenAI Integration Review

**Date:** 2026-03-01
**Scope:** `ai.py`, `tagger.py`, `importer.py`, `cli/commands/tag.py`, `tagging_config.json`, test suites
**Skill reference:** `.github/skills/openai-vision-api/SKILL.md`

---

## Executive Summary

The OpenAI integration is well-structured with proper client caching, layered configuration, telemetry tracking, and a clean separation between the ChatGPT backend API and the official OpenAI API. The code uses the newer Responses API (`client.responses.create`) rather than the Chat Completions API documented in the skill file. Primary concerns are: incomplete error handling (only `RateLimitError` is caught), no image size optimization before encoding, missing `max_tokens` constraint on API responses, and lack of per-image failure isolation in the batch tagger. The skill file is out of date with the actual implementation.

---

## 1. API Client Management

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L17-L44)

### Strengths

- **Cached client pattern** implemented exactly as the skill prescribes — `_CLIENT_CACHE` dict keyed by API key string, reused across calls.
- `reset_client_cache()` exposed for test cleanup.
- All feature code uses `get_cached_client()` — no direct `OpenAI()` construction found in `tagger.py` or `importer.py`.

### Concerns

- **No connection pooling configuration.** The `OpenAI` client defaults are used without setting `max_retries=0` at the client level (the code does its own retry loop, so the SDK's built-in retries could double up). The SDK's default `max_retries` is 2, meaning a rate-limited request could retry up to **2 (SDK) × 3 (code) = 6** times.
- **No client timeout configuration.** Long-running vision API calls could hang indefinitely. Consider setting `timeout=httpx.Timeout(60.0, connect=10.0)` when constructing the client.
- **Cache has no eviction.** If different API keys are used over time, old clients linger. Minor concern for a CLI tool.

### Recommendation

```python
client = OpenAI(api_key=api_key, max_retries=0, timeout=60.0)
```

Set `max_retries=0` on the SDK client since `call_image_endpoint` does its own retry loop. Add a reasonable timeout. **Priority: Medium.**

---

## 2. Rate Limiting

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L118-L146)

### Strengths

- Exponential backoff implemented: starts at 1.0s, doubles each retry, up to `max_retries=3`.
- `on_retry` callback allows the caller to log retry events.
- Retry count captured in `AIRequestTelemetry.retries`.

### Concerns

- **`Retry-After` header not respected.** The skill explicitly calls this out. The OpenAI error response includes timing hints that are ignored.
- **Base delay of 1.0s** is more aggressive than the skill's recommended 2.0s. With the SDK's own retries potentially stacking (see §1), this could lead to rapid-fire retries.
- **No RPM/TPM awareness.** Concurrent workers (`max_workers=4` default) send requests as fast as possible. With large image batches, this can easily exceed tier rate limits. There's no throttle, semaphore, or token bucket.
- **Only `RateLimitError` is caught** in the retry loop. `APIConnectionError` and `APITimeoutError` are also transient and should be retried.

### Recommendation

1. Check `err.response.headers.get("Retry-After")` and use it when present.
2. Increase base delay to 2.0s.
3. Add `APIConnectionError` and `APITimeoutError` to the retry catch.
4. Consider a simple rate limiter (e.g., `time.sleep(0.5)` between calls) when `max_workers > 1`.

**Priority: High** — rate limit storms in batch tagging are the most likely production failure.

---

## 3. Prompt Engineering

**Files:** [tagger.py](src/chatgpt_library_archiver/tagger.py#L23-L26), [importer.py](src/chatgpt_library_archiver/importer.py#L35-L37), `tagging_config.json`

### Tagging Prompt (default)

```
Generate concise, comma-separated descriptive tags for this image
in the style of booru archives.
```

**Analysis:**
- Requests structured output (comma-separated) — good for parsing.
- References a known tagging style (booru) — provides vocabulary consistency.
- Concise — minimizes prompt tokens.
- The user's `tagging_config.json` overrides this with a much more detailed prompt requesting thorough analysis of features, moods, colors, species, etc. This layered override works correctly.

### Rename Prompt (default)

```
Create a short, descriptive filename slug (kebab-case, <=6 words) for this image.
```

**Analysis:**
- Constrains output format and length.
- `_slugify()` in `importer.py` normalizes the result, providing defense against non-conforming output.
- Well-designed for the use case.

### Concerns

- **No system prompt.** Both prompts are sent as user messages. A system prompt could enforce output format more reliably (e.g., "You are a tagging assistant. Always respond with only comma-separated tags, nothing else.").
- **No `max_tokens` set** on the API call (see §5). The model could return arbitrarily long responses, consuming unnecessary tokens.
- **No few-shot examples.** For tagging, one or two examples would improve consistency across diverse image types.

### Recommendation

Add a system-level instruction constraining output format, and set `max_tokens` to cap response length. **Priority: Medium.**

---

## 4. Error Handling

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L118-L146), [tagger.py](src/chatgpt_library_archiver/tagger.py#L128-L157), [importer.py](src/chatgpt_library_archiver/importer.py#L226-L244)

### Strengths

- `RateLimitError` handled with retry in `call_image_endpoint`.
- In `importer.py`, the `_generate_ai_slug()` call is wrapped in `except Exception` — if AI rename fails, it falls back to slugifying the original filename. This is proper graceful degradation.

### Concerns

- **No handling for `AuthenticationError`.** An invalid API key will produce an unhelpful traceback rather than a clear message like "Invalid API key. Check tagging_config.json."
- **No handling for `BadRequestError`.** Content filtering rejections (flagged images) will crash the process instead of skipping the image.
- **No handling for `APIConnectionError` or `APITimeoutError`.** Network blips will not retry.
- **Thread pool exception propagation in `tagger.py`.** At [tagger.py line 152](src/chatgpt_library_archiver/tagger.py#L152), `fut.result()` is called without a `try/except`. A single image failure (e.g., content filter, corrupt file) aborts the entire batch. Compare to `importer.py` which wraps AI calls in `except Exception`.
- **No `output_text` validation.** The code calls `response.output_text.strip()` without checking that `output_text` exists or is non-empty. A content-filtered response or unexpected API change could raise `AttributeError`.

### Recommendation

1. Wrap individual image processing in `tagger.py`'s thread pool with `try/except`, log failures, and continue.
2. Catch `AuthenticationError` early in `ensure_tagging_config` or at the first API call to provide a clear error message.
3. Add `BadRequestError` handling to skip images flagged by content filtering.
4. Validate `response.output_text` before accessing.

**Priority: High** — a single bad image can crash a multi-hundred-image tagging run.

---

## 5. Cost Management

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L99-L111), [tagger.py](src/chatgpt_library_archiver/tagger.py#L128-L165)

### Strengths

- Token usage tracked per request via `AIRequestTelemetry`.
- Aggregate token count and average latency reported at end of batch.
- `re_tag=False` default skips already-tagged images — avoids redundant API calls.
- `telemetry_sink` callback allows external aggregation.

### Concerns

- **No `max_tokens` parameter** on `responses.create`. The model defaults to its maximum output length. For tagging (expected: ~50 tokens) and renaming (expected: ~10 tokens), this wastes completion budget and risks inflated costs. The skill recommends `max_tokens=300`.
- **Full-resolution images sent.** Base64 encoding the original image (potentially 5–20 MB) results in massive payloads and high input token counts. The vision API charges per image tile; a 4096×4096 image costs significantly more tokens than a 512×512 one. There's no downscaling or use of the `detail` parameter.
- **No budget/cost cap.** No mechanism to stop after N tokens or N dollars.
- **No caching of AI results.** If a run is interrupted and restarted with `--all`, previously tagged images are re-tagged. The `re_tag=False` default mitigates this for normal runs, but explicit `--all` re-tags everything.

### Recommendation

1. Set `max_tokens=300` for tagging, `max_tokens=50` for renaming.
2. Resize images to ≤1024px on the longest edge before encoding, or use the `detail: "low"` parameter to force low-res processing (fixed 85 tokens per image).
3. Consider a `--max-cost` or `--max-images` flag for budget control.

**Priority: High** — image encoding without size optimization is the largest unnecessary cost driver.

---

## 6. Response Parsing

**Files:** [tagger.py](src/chatgpt_library_archiver/tagger.py#L91-L93), [importer.py](src/chatgpt_library_archiver/importer.py#L66-L70)

### Tagging

```python
parts = [p.strip() for p in text.replace("\n", ",").split(",")]
tags = [p for p in parts if p]
```

**Analysis:** Handles comma-separated and newline-separated output. Strips whitespace. Filters empty strings. Simple and effective.

### Renaming

```python
slug = _slugify(text)
```

**Analysis:** `_slugify()` normalizes Unicode, lowercases, replaces non-alphanumeric with hyphens, strips leading/trailing hyphens. Robust against non-conforming AI output.

### Concerns

- **No tag deduplication.** If the model returns duplicates, they're stored as-is.
- **No tag normalization** (e.g., lowercase, canonical forms). "Cat" and "cat" would be stored as separate tags.
- **No length validation.** An unexpectedly long tag list or a single run-on tag string isn't capped.
- **No validation that tags are reasonable** (e.g., checking for model refusal messages like "I can't analyze this image" being stored as a tag).

### Recommendation

Add lowercase normalization and deduplication. Consider a max tag count (e.g., 50). Check for known refusal patterns. **Priority: Low** — current parsing works well for normal responses.

---

## 7. Configuration

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L54-L98), [tagger.py](src/chatgpt_library_archiver/tagger.py#L40-L76)

### Strengths

- **Layered resolution** with clear priority: CLI args → environment variables → config file → defaults.
- **Three environment variable names** for the API key: `CHATGPT_LIBRARY_ARCHIVER_OPENAI_API_KEY`, `CHATGPT_LIBRARY_ARCHIVER_API_KEY`, `OPENAI_API_KEY` — flexible for different setups.
- **Environment overrides** for model, tag prompt, and rename prompt.
- **Interactive config creation** with `--no-config-prompt` to disable for CI.
- **API key override rejection** (`resolve_config` raises `ValueError` if `overrides` contains `api_key`) — prevents accidental key passing through code.

### Concerns

- **No config validation.** The `model` field accepts any string without checking against known model IDs. An invalid model will fail at API call time instead of at config load.
- **No CLI flag for `rename_prompt`** in `tag.py` (only in `import_command.py`). Asymmetric.
- **`tagging_config.json` example not provided.** There's an `auth.txt.example` but no `tagging_config.json.example` to guide users.

### Recommendation

Add a `tagging_config.json.example` file. Consider model validation or at least a warning for unrecognized model strings. **Priority: Low.**

---

## 8. Image Encoding

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L99-L111)

```python
def encode_image(image_path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    with image_path.open("rb") as fh:
        payload = base64.b64encode(fh.read()).decode("ascii")
    data_url = f"data:{mime};base64,{payload}"
    return mime, data_url
```

### Strengths

- MIME type detection via `mimetypes.guess_type` with sensible fallback.
- Standard base64 data URL format.
- Returns both MIME type and data URL for flexibility.

### Concerns

- **No size optimization.** Full original images are read, encoded, and sent. A 10 MB JPEG becomes ~13.3 MB of base64 text in the API payload. This:
  - Increases input token count (vision API charges per 512×512 tile)
  - Slows upload time
  - May exceed API payload limits (20 MB for some endpoints)
- **No format conversion.** BMP and TIFF files (supported by the importer) are large formats that should be converted to JPEG/WebP before encoding.
- **No validation.** Corrupt or zero-byte files will produce invalid base64 payloads. The error will surface as a confusing API error rather than a clear local message.
- **Memory usage.** Entire file loaded into memory, then base64-encoded (1.33× size). For batch processing of large images, this could be significant.

### Recommendation

1. Resize images to ≤1024px (or ≤2048px) before encoding using Pillow (already a dependency for thumbnails).
2. Convert BMP/TIFF to JPEG before encoding.
3. Validate file size and format before encoding.
4. Consider using the `detail: "low"` parameter in the API call for cost-sensitive batch operations.

**Priority: High** — this is the single highest-impact optimization for cost and performance.

---

## 9. Telemetry & Logging

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L20-L33), [tagger.py](src/chatgpt_library_archiver/tagger.py#L128-L165)

### Strengths

- `AIRequestTelemetry` dataclass captures: operation, subject, latency, prompt tokens, completion tokens, total tokens, retries.
- Per-image telemetry logged with `StatusReporter` (tokens and latency).
- Aggregate summary at batch end: total tokens and average latency.
- `telemetry_sink` callback for external consumption.
- Progress bar via `tqdm` through `StatusReporter`.

### Concerns

- **No cost estimation.** Token counts are reported but not translated to estimated cost. Even a rough `tokens × $0.XX / 1M` calculation would help users understand spend.
- **No success/failure rate tracking.** If images fail (content filter, timeout), there's no summary count of successes vs. failures.
- **No persistent telemetry log.** Telemetry is displayed in stdout but not written to a file. For large batches or CI runs, historical tracking is impossible.
- **No model name in telemetry.** The `AIRequestTelemetry` dataclass doesn't record which model was used, making it harder to compare costs across models.

### Recommendation

Add model to telemetry, add a cost estimate in the summary, and consider writing telemetry to a JSON file. **Priority: Low.**

---

## 10. Security

**Files:** [ai.py](src/chatgpt_library_archiver/ai.py#L54-L98), [.gitignore](.gitignore#L28)

### Strengths

- `tagging_config.json` is in `.gitignore` — API keys won't be committed.
- `auth.txt` is also gitignored.
- `resolve_config` rejects API key overrides via code — keys can only come from file or environment.
- No API key logging found in any log statements.

### Concerns

- **Committed `tagging_config.json` observable in workspace.** While gitignored, the workspace file tree shows it with an actual API key starting with `sk-Zpp16...`. If anyone historically committed this file before the gitignore was added, the key is in Git history. **Rotate this key immediately.**
- **No key format validation.** A malformed key (e.g., pasted with trailing whitespace or quotes) will produce a confusing `AuthenticationError` instead of a clear "invalid key format" message.
- **No key scope/permission documentation.** Users aren't told what API permissions the key needs (just Chat Completions / Responses access; no fine-tuning, no file upload).
- **API key in `_write_config` echo.** During interactive config creation, the API key is typed into stdin in cleartext. There's no masking with `getpass`.

### Recommendation

1. **Rotate the API key** in `tagging_config.json` immediately. Verify it was never committed to Git history: `git log --all --diff-filter=A -- tagging_config.json`.
2. Use `getpass.getpass("api_key = ")` in `_write_config` for masked input.
3. Add key format validation (should start with `sk-` and meet minimum length).
4. Document required API key permissions in README.

**Priority: Critical** (key rotation), **Medium** (other items).

---

## 11. Resilience

### Strengths

- `importer.py` wraps AI rename in `except Exception` with fallback to filename-based slug — proper graceful degradation.
- Tag removal operations (`--remove-all`, `--remove-ids`) don't require OpenAI at all.
- `ensure_tagging_config` falls through multiple config sources before failing.

### Concerns

- **Tagger batch failure mode.** In `tagger.py`, the `ThreadPoolExecutor` submits all items, then iterates `as_completed`. If any future raises (network error, content filter, corrupt image), `fut.result()` raises and the entire batch aborts. Already-tagged items in that batch are lost because `save_gallery_items` is only called once at the end.
- **No partial save.** If the process is killed mid-batch or an error occurs, all tagging work from that run is lost.
- **No graceful shutdown.** No signal handler for SIGINT/SIGTERM to save progress before exiting.
- **No health check.** There's no way to verify the API key works before starting a multi-hour tagging run. A bad key wastes time encoding images before the first call fails.

### Recommendation

1. Wrap `fut.result()` in `try/except` in `tagger.py`, log the failure, and continue.
2. Periodically save metadata (e.g., every 10 images) to avoid losing work.
3. Add a `--dry-run` or health-check API call before starting the batch.

**Priority: High** — batch failure without partial save is a significant usability issue.

---

## 12. Alignment with Skill File

The skill file (`.github/skills/openai-vision-api/SKILL.md`) documents patterns that diverge from the current implementation in several ways:

| Aspect | Skill File | Implementation | Status |
|--------|-----------|----------------|--------|
| API endpoint | `chat.completions.create` | `responses.create` | **Skill outdated** |
| Content type (text) | `{"type": "text", ...}` | `{"type": "input_text", ...}` | **Skill outdated** |
| Content type (image) | `{"type": "image_url", ...}` | `{"type": "input_image", ...}` | **Skill outdated** |
| `max_tokens` | `300` | Not set | **Implementation gap** |
| Base retry delay | `2.0s` | `1.0s` | **Minor divergence** |
| Image encode return | `(base64_data, media_type)` | `(mime, data_url)` | **Skill outdated** |
| `Retry-After` header | Recommended | Not implemented | **Implementation gap** |

The implementation has migrated to the newer OpenAI Responses API (`responses.create` with `input_text`/`input_image` content types) while the skill still documents the Chat Completions API. **The skill file should be updated** to reflect the current Responses API patterns.

---

## Prioritized Recommendations

### Critical

| # | Issue | Files | Effort |
|---|-------|-------|--------|
| 1 | Rotate leaked API key in `tagging_config.json`, verify Git history | `tagging_config.json` | Immediate |

### High

| # | Issue | Files | Effort |
|---|-------|-------|--------|
| 2 | Resize images before encoding (≤1024px) to reduce token cost | `ai.py` | Small |
| 3 | Set `max_tokens` on API calls (300 for tags, 50 for rename) | `ai.py` | Trivial |
| 4 | Wrap thread pool `fut.result()` in try/except for per-image isolation | `tagger.py` | Small |
| 5 | Catch `APIConnectionError`, `APITimeoutError` in retry loop | `ai.py` | Small |
| 6 | Set `max_retries=0` on `OpenAI()` to prevent double retries | `ai.py` | Trivial |
| 7 | Increase base retry delay to 2.0s, respect `Retry-After` header | `ai.py` | Small |
| 8 | Periodic metadata save during batch tagging | `tagger.py` | Medium |

### Medium

| # | Issue | Files | Effort |
|---|-------|-------|--------|
| 9 | Add `AuthenticationError` / `BadRequestError` handling with clear messages | `ai.py`, `tagger.py` | Small |
| 10 | Use `getpass` for interactive API key input | `tagger.py` | Trivial |
| 11 | Add client timeout configuration | `ai.py` | Trivial |
| 12 | Validate `response.output_text` before accessing | `ai.py` | Trivial |
| 13 | Update skill file to document Responses API patterns | `SKILL.md` | Medium |

### Low

| # | Issue | Files | Effort |
|---|-------|-------|--------|
| 14 | Add tag deduplication and lowercase normalization | `tagger.py` | Trivial |
| 15 | Add model name to `AIRequestTelemetry` | `ai.py` | Trivial |
| 16 | Create `tagging_config.json.example` | Root | Trivial |
| 17 | Add cost estimation to telemetry summary | `tagger.py` | Small |
| 18 | Add API health check before batch start | `tagger.py` | Small |

---

## Test Coverage Assessment

**Files:** [test_ai.py](tests/test_ai.py), [test_tagger.py](tests/test_tagger.py)

### Covered

- Client caching and reuse (`test_get_cached_client_reuses_instance`)
- Config resolution with env override priority (`test_resolve_config_prefers_env_and_model_override`)
- API key override rejection (`test_resolve_config_rejects_api_key_override`)
- Rate limit retry with backoff (`test_call_image_endpoint_retries`)
- Tag only untagged images (`test_tag_missing_only`)
- Re-tag all images (`test_retag_all`)
- Tag specific IDs (`test_tag_specific_ids`)
- Remove all tags / specific IDs (`test_remove_all_tags`, `test_remove_specific_ids`)
- Progress and token reporting (`test_progress_and_tokens`)
- Config from env with no file (`test_ensure_tagging_config_respects_env`)
- Missing config in non-interactive mode (`test_ensure_tagging_config_missing_non_interactive`)

### Missing

- **No test for `encode_image`.** MIME detection, base64 encoding, and data URL construction are untested.
- **No test for API errors other than `RateLimitError`** (timeout, connection, auth, content filter).
- **No test for `max_retries` exhaustion** — what happens when all retries fail.
- **No test for malformed API response** (missing `output_text`, empty response).
- **No test for concurrent tagging** — thread pool behavior, race conditions.
- **No test for the rename flow** in `importer.py` with AI enabled.
- **No test for the `telemetry_sink` callback** in `tag_images`.
- **No integration test** verifying end-to-end flow with a mock OpenAI server.
