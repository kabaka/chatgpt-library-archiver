# Security Audit Report — chatgpt-library-archiver

**Audit Date:** 2026-03-01
**Auditor:** Security Auditor (automated)
**Scope:** Full codebase review of `src/chatgpt_library_archiver/` and supporting configuration files
**Commit Range:** Current working tree (HEAD)
**Updated:** 2026-03-01 — Incorporated cross-review findings from Architecture, UX, and AI integration perspectives

---

## Executive Summary

The chatgpt-library-archiver is a local CLI tool that handles sensitive authentication tokens (ChatGPT Bearer tokens, session cookies) and OpenAI API keys. Overall, the project demonstrates **good security awareness** — credentials are masked in output, file permissions are considered, `.gitignore` covers sensitive files, and TLS verification is never disabled.

However, several issues were identified ranging from **Critical** (live credentials committed to files, API key stored world-readable) to **High** (XSS via `innerHTML`, missing redirect credential stripping, no download size limits, non-atomic metadata writes) to **Medium** (path traversal, Pillow decompression bombs, OpenAI SDK debug logging, tagger batch abort) to **Low/Informational** (API key memcache, signed URLs in metadata, echoed credentials, missing Content-Type enforcement, symlink risks).

Cross-review analysis also revealed AI-specific security concerns: the OpenAI SDK can log API keys at DEBUG level, base64-encoded user images persist in process memory/core dumps, and AI-generated tags create a chained XSS vector through `metadata.json` into the gallery's `innerHTML`.

### Severity Summary

| Severity | Count |
|----------|-------|
| **Critical** | 2 |
| **High** | 4 |
| **Medium** | 6 |
| **Low** | 6 |
| **Informational** | 4 |

*Changes from original audit: M-5 upgraded to High (H-4). Three new AI-specific findings added (M-5 Medium, M-6 Medium, L-6 Low).*

---

## Critical Findings

### C-1: Live OpenAI API Key in `tagging_config.json` with World-Readable Permissions

**Severity:** Critical
**File:** `tagging_config.json` (project root)

The `tagging_config.json` file contains a **real OpenAI API key** and has permissions `644` (owner read/write, group read, world read):

```json
{
  "api_key": "sk-YOUR-KEY-HERE",
  "prompt": "Generate concise, comma-separated descriptive tags..."
}
```

```
$ stat -f "%Sp" tagging_config.json
-rw-r--r--
```

While `auth.txt` is correctly created with `0o600` permissions via `os.open()` with explicit mode, `tagging_config.json` is written using plain `open()` which inherits the default umask (typically `022` → `644`).

**Code creating the file without secure permissions:**

```python
# src/chatgpt_library_archiver/tagger.py:42-43
def _write_config(path: str) -> dict:
    # ...
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
```

**Impact:** Any local user on the system can read the OpenAI API key, which has billing implications.

**Remediation:**
1. **Immediately rotate the exposed API key** at https://platform.openai.com/api-keys
2. Change `_write_config()` to use `os.open()` with `0o600` mode, matching the `auth.txt` pattern:
   ```python
   fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
   with os.fdopen(fd, "w", encoding="utf-8") as f:
       json.dump(cfg, f, indent=2)
   ```
3. Fix permissions of the existing file: `chmod 600 tagging_config.json`

#### Cross-Review Insights

**Architecture perspective:** Rather than scattering `os.open()` with `0o600` across every module that writes sensitive files, extract a shared `write_secure_file()` helper in `utils.py`. Both `tagger._write_config()` and the auth-writing code should delegate to it. This centralizes the permission logic and prevents future modules from forgetting to set permissions. The helper can later be upgraded to atomic writes (see H-4), benefiting all callers at once.

**AI perspective:** OpenAI API keys cannot be scoped to specific endpoints. A key valid for `responses.create` is also valid for fine-tuning, file uploads, and model management. Unlike the browser token in C-2 (which has specific scopes and expires), an API key remains valid until manually rotated. The financial exposure is effectively unlimited within the OpenAI platform. Consider adding an `sk-` prefix validation when reading the config to catch obviously malformed keys early.

---

### C-2: Live Credentials Present in `auth.txt`

**Severity:** Critical
**File:** `auth.txt` (project root)

The `auth.txt` file contains a live Bearer token (JWT) and session cookie. While the file:
- ✅ Has correct `600` permissions
- ✅ Is in `.gitignore`
- ✅ Is not tracked by git

The JWT payload (decoded from the authorization header) reveals:
- **User ID:** `user-WSwEmmTnYhBiHxOqWraOy6vv`
- **Email:** `openai.com@kyle.engineer`
- **Session ID:** `authsess_O6VRSZL8RkgczTwUaZOr66qi`
- **Expiry:** Included in the `exp` claim

The token was issued with scopes including `organization.write`, meaning compromise would allow modification of the user's OpenAI organization settings.

**Remediation:**
1. This is working as designed for a local CLI tool, but the token's broad scope (`organization.write`) is a concern
2. Consider documenting the minimum required scopes
3. Consider implementing token expiry detection to warn users when tokens are stale

---

## High Findings

### H-1: Gallery HTML Uses `innerHTML` with Unsanitized Metadata — XSS Risk

**Severity:** High
**File:** `src/chatgpt_library_archiver/gallery_index.html:441-450`

The gallery viewer builds HTML using string concatenation and `innerHTML`, injecting metadata values (title, tags, conversation links, filenames) without escaping:

```javascript
card.innerHTML =
  '<a href="' + imgPath + '" class="thumb">' +
  '<img data-src="' + thumbPath + '" ... alt="' + title + '" loading="lazy"></a>' +
  '<div class="meta"><strong>' + (title || item.id) + '</strong>' +
  '<span class="created"><br>' + created + '</span>' +
  tagsHtml + '<br><a href="' +
  (item.conversation_link || '#') +
  '" target="_blank">View conversation</a></div>';
```

If an attacker can inject content into `metadata.json` (e.g., via a crafted API response, or by modifying the JSON file directly), they can inject arbitrary HTML/JavaScript. For example, a title of `<img src=x onerror=alert(1)>` would execute JavaScript.

**Attack vectors:**
1. **Malicious API response:** If ChatGPT's API returns a crafted `title` field containing HTML
2. **Metadata file tampering:** Direct modification of `gallery/metadata.json`
3. **Tag injection:** Tags are also inserted via `innerHTML` without escaping

**Affected metadata fields injected unsafely:**
- `title` (lines 441, 444)
- `tags` (line 438 — `tagsSnippet`)
- `conversation_link` (line 447)
- `filename` (via `imgPath`, line 441)
- `item.id` (line 444)
- `thumbnail` paths (line 442)

**Remediation:**
Replace `innerHTML` with `document.createElement()` / `textContent` for all user/metadata-derived content. At minimum, implement an HTML escape function:

```javascript
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
```

And apply it to all interpolated values: `escapeHtml(title)`, `escapeHtml(tagsSnippet)`, etc. For `href` attributes, validate that URLs start with `https://` or are `#`.

#### Cross-Review Insights

**Architecture perspective (preferred approach):** Since the gallery is a single-file bundled template with vanilla JS (no framework), the cleaner architectural approach is to build DOM nodes procedurally with `document.createElement()` and `textContent` assignments, eliminating `innerHTML` entirely for metadata-derived content. The `escapeHtml()` utility is a half-measure that still allows developers to accidentally skip it. A `buildCard(item)` function that returns a `DocumentFragment` makes the "safe by default" intent explicit. This is more verbose but eliminates the entire class of injection bugs. For `href` attributes, add a `safeHref()` helper:

```javascript
function safeHref(url) {
  if (!url) return '#';
  try { const u = new URL(url); return ['https:', 'http:'].includes(u.protocol) ? url : '#'; }
  catch { return '#'; }
}
```

**AI perspective (chained XSS vector):** The `response.output_text` from OpenAI's vision API is used unsanitized as tag data in `tagger.py` lines 109–110 and persisted to `metadata.json`. If the API returns unexpected content (model refusal text, prompt injection from a crafted image, or API error text), that content flows: **API response → tags → metadata.json → innerHTML → XSS**. The probability is low (it requires crafting an image that causes the model to output HTML), but the chain exists. Defense in depth: strip HTML-like content from tags at generation time AND escape at render time:

```python
import re
tags = [re.sub(r'<[^>]+>', '', p) for p in parts if p]
```

**UX perspective (remediation has no UX downside):** The `createElement()`/`textContent` refactor produces identical visible output. Both approaches have no meaningful performance penalty for 1,000+ cards when batched via `DocumentFragment`. The refactor is also a natural moment to add semantic HTML (`<article>` wrappers), clickable tag chips, and accessible focus styling — turning a security fix into a UX improvement.

**UX perspective (`conversation_link` display):** When a `conversation_link` URL is sanitized to `#`, clicking "View conversation" scrolls to the page top — confusing behavior. Better UX: hide the link entirely when the URL is invalid:

```javascript
if (safeHref(item.conversation_link) !== '#') {
  // render the link
}
```

**UX perspective (`file://` edge case):** If the gallery is opened via `file://`, the strict `safeHref()` allowlist (`['http:', 'https:']`) would block all image and conversation links. The `file:` protocol does not enable script injection, so it is safe to include. Alternatively, a blocklist approach (`javascript:`, `data:`, `vbscript:`) preserves broader compatibility:

```javascript
const BLOCKED_SCHEMES = new Set(['javascript:', 'data:', 'vbscript:']);
function safeHref(url) {
  if (!url || url === '#') return '#';
  try {
    const parsed = new URL(url, location.href);
    if (BLOCKED_SCHEMES.has(parsed.protocol)) return '#';
    return url;
  } catch (e) {
    if (url.startsWith('images/') || url.startsWith('thumbs/')) return url;
    return '#';
  }
}
```

---

### H-2: HTTP Client Does Not Strip Auth Headers on Redirects

**Severity:** High
**File:** `src/chatgpt_library_archiver/http_client.py` (entire class)

The `HttpClient` class uses `requests.Session` with default redirect-following behavior. When `stream_download()` or `get_json()` is called, `requests` will automatically follow redirects (301, 302, etc.) and **forward all headers — including `Authorization: Bearer ...` and `Cookie` headers — to the redirect target**.

If the ChatGPT API were to return a redirect to a third-party domain, the Bearer token and session cookie would be leaked.

**Code in** `http_client.py:140-141`:
```python
response = self._get_session().get(url, headers=headers, timeout=self.timeout)
```

No `allow_redirects=False` is set in `get_json()` or `stream_download()`.

**Note:** The `browser_extract.py` module correctly uses `allow_redirects=False` for its token-exchange requests (lines 358, 430), demonstrating awareness of this risk — but the same protection is not applied to the main download client.

**Remediation:**
1. Configure `requests.Session` to not send auth headers on cross-domain redirects. The `requests` library (2.32+) supports `Session.rebuild_auth()` which is called automatically on redirects to strip `Authorization` when redirecting to a different host. However, this only covers `Authorization`, not `Cookie`. The most reliable fix requires manual handling.
2. Or set `allow_redirects=False` and handle redirects manually, stripping `Authorization` and `Cookie` headers if the redirect target is a different origin.

#### Cross-Review Insights

**Architecture perspective (separated redirect strategies):** The cleanest architectural approach separates the two use cases:

1. **For `get_json()` (API calls):** Set `allow_redirects=False`. The ChatGPT API should not redirect; a redirect is unexpected behavior and should be raised as an error.
2. **For `stream_download()` (image downloads):** Image downloads from CDN URLs may legitimately redirect. Use a custom redirect loop that strips both `Authorization` and `Cookie` headers on cross-origin redirects.

This separates the two use cases architecturally rather than applying a one-size-fits-all fix. Note: the originally proposed `session.max_redirects = 5` approach only limits chain length — it doesn't address credential leakage.

**AI perspective:** This finding does not affect OpenAI API calls, which go through the SDK (not raw `requests`), so the redirect risk is correctly scoped to the ChatGPT backend API and CDN download paths only.

---

### H-3: No Download Size Limit — Potential Disk Exhaustion

**Severity:** High
**File:** `src/chatgpt_library_archiver/http_client.py:200-230`

The `stream_download()` method streams response data to disk without any maximum size check:

```python
with destination.open("wb") as fh:
    for chunk in response.iter_content(chunk_size=chunk_size):
        if not chunk:
            continue
        fh.write(chunk)
        hasher.update(chunk)
        bytes_downloaded += len(chunk)
```

A malicious or compromised server could send an infinite response, filling the disk.

**Remediation:**
Add a configurable maximum download size (e.g., 100 MB for images):
```python
MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100MB

# Inside the loop:
if bytes_downloaded > MAX_DOWNLOAD_SIZE:
    destination.unlink(missing_ok=True)
    raise HttpError(url=url, reason="Download exceeds maximum size limit", ...)
```

#### Cross-Review Insights

**Architecture perspective:** The limit should be a parameter on `stream_download()` rather than a module-level constant:

```python
def stream_download(self, url, destination, *, max_bytes: int | None = None, ...):
```

This keeps `HttpClient` generic (it's also used for metadata fetches) and lets callers specify context-appropriate limits — image downloads would pass `100 * 1024 * 1024`, while metadata fetches might use `10 * 1024 * 1024`.

**UX perspective:** The error message matters. When a download is rejected for size, the CLI should communicate clearly: "Skipped image X: download exceeded 100 MB limit." Users should not see a raw traceback or opaque `HttpError`. Consider a `--max-image-size` CLI flag so power users can override the default. DALL-E 3 images at maximum resolution can be 4–8 MB, so a 100 MB limit is safely generous.

---

### H-4: `metadata.json` Written Without Atomic Replacement

**Severity:** High *(upgraded from Medium)*
**File:** `src/chatgpt_library_archiver/metadata.py:206-210`

```python
def save_gallery_items(gallery_root, items):
    path = metadata_path(gallery_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([item.to_dict() for item in items], fh, indent=2)
```

If the process is interrupted during `json.dump()`, the file will be left in a corrupt state (partially written). Since `metadata.json` is the source of truth for the entire gallery, this could result in data loss.

**Remediation:**
Write to a temporary file and atomically rename:
```python
import tempfile
tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
try:
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
        json.dump([item.to_dict() for item in items], fh, indent=2)
    os.replace(tmp_path, path)
except:
    os.unlink(tmp_path)
    raise
```

#### Severity Upgrade Rationale

This finding was originally rated Medium (M-5). Cross-review analysis from three independent perspectives supports upgrading to High:

**Architecture perspective (strong advocate for upgrade):** `metadata.json` is the single source of truth for the entire gallery. The `json.dump()` directly into the target file means a `SIGKILL` during write loses all metadata. The downloader calls `save_gallery_items()` after downloading all images — if a batch download of 100 images completes but the metadata write is interrupted, the user loses the entire metadata record. The images exist on disk but the gallery has no record of them. This is a **data-loss scenario** more likely to occur than some security findings ranked above it.

**AI perspective (compounding risk):** The AI tagger also writes to the same `metadata.json` via `save_gallery_items()` at the end of batch tagging. Implementing periodic saves during tagging (a recommended optimization) without fixing atomic writes first would *increase* the corruption window. The atomic write fix is a prerequisite for safe incremental saves.

**UX perspective:** A corrupted `metadata.json` causes the gallery to show nothing — a blank page with no error indication. The atomic write fix (prevention) should be paired with gallery-side error handling (graceful degradation):

```javascript
try {
  const items = await response.json();
} catch (e) {
  showError('metadata.json appears to be corrupted. Try re-running the download command.');
}
```

---

## Medium Findings

### M-1: API Key Used as Dictionary Key in Memory Cache

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/ai.py:18-41`

```python
_CLIENT_CACHE: dict[str, OpenAI] = {}

def get_cached_client(api_key: str) -> OpenAI:
    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = OpenAI(api_key=api_key)
        _CLIENT_CACHE[api_key] = client
    return client
```

The API key is used as a dictionary key and remains in memory for the lifetime of the process. While Python strings are immutable and will be garbage-collected eventually, the cache itself holds a permanent reference, meaning the key can be found via memory inspection or core dumps.

**Remediation:**
Use a hash of the API key as the cache key instead:
```python
import hashlib
cache_key = hashlib.sha256(api_key.encode()).hexdigest()
_CLIENT_CACHE[cache_key] = client
```

#### Cross-Review Insights

**AI perspective (limited practical impact):** The `OpenAI` client object *itself* holds the API key in memory as `client.api_key`, so hashing the cache key removes one copy but not the primary one. For a CLI tool with a single-process lifecycle, the practical risk is low. The benefit is more about code hygiene than substantive protection.

**Architecture perspective (lightweight hash):** If implemented, prefer `hashlib.blake2b(api_key.encode(), digest_size=16).hexdigest()` rather than SHA-256 — faster and equally suitable for cache keying.

**Architecture perspective (thread safety):** The `get_cached_client()` function reads and writes `_CLIENT_CACHE` without synchronization. The `tagger.py` module uses `ThreadPoolExecutor` and calls `get_cached_client()` from worker threads. Python's GIL makes dict operations thread-safe at the bytecode level, but this is an implementation detail, not a guarantee. A `threading.Lock` or `functools.lru_cache` would be more correct.

---

### M-2: Signed Download URLs Persisted in `metadata.json`

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/metadata.py` → `GalleryItem.url` field, `src/chatgpt_library_archiver/incremental_downloader.py:157`

Download URLs from ChatGPT's API are stored permanently in `metadata.json`:

```json
"url": "https://chatgpt.com/backend-api/estuary/content?id=file_...&sig=9c9cd3c672..."
```

These URLs contain signed parameters (`sig`, `ts`, `ma`) that, while time-limited, reveal:
- Internal file IDs
- Signing parameters
- API endpoint structure

Since `gallery/` is in `.gitignore`, this is primarily a concern if the gallery directory is shared or hosted publicly (e.g., on a static web server serving `metadata.json`).

**Remediation:**
Consider stripping URL query parameters after successful download, or not persisting the URL at all once the file is saved locally. Add a note in documentation warning against publicly hosting the `metadata.json` file.

---

### M-3: No Path Traversal Protection on Downloaded Filenames

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/incremental_downloader.py:97-105`

Downloaded images are saved with filenames derived from the API-provided `id`:

```python
filename = f"{item.id}{ext}"
filepath = images_dir / filename
```

While the `item.id` from the ChatGPT API is typically a hex string like `s_1ef6...`, there is no validation that `item.id` doesn't contain path separators. A malicious API response with `id: "../../etc/cron.d/evil"` could write files outside the gallery directory.

**The importer has better protection** via `_slugify()` which strips non-alphanumeric characters, but the downloader does not apply similar sanitization.

**Remediation:**
Validate that the computed `filename` does not contain path separators and that the resolved path is within the expected directory:
```python
filename = f"{item.id}{ext}"
filepath = (images_dir / filename).resolve()
if not filepath.is_relative_to(images_dir.resolve()):
    raise ValueError(f"Path traversal detected in filename: {filename}")
```

#### Cross-Review Insights

**Architecture perspective:** The importer's `_slugify()` approach is the superior pattern because it prevents the problem at the source rather than detecting it after construction:

```python
import re
def _safe_filename(image_id: str, ext: str) -> str:
    clean = re.sub(r'[^\w\-.]', '_', image_id)
    return f"{clean}{ext}"
```

Prefer defense in depth: sanitize the input *and* verify the resolved path. This is arguably under-rated at Medium.

**UX perspective:** The error message "Path traversal detected in filename: {filename}" is too technical for end users. Prefer: "Skipped image: invalid filename." Security error messages visible to users should follow the pattern `Skipped {item}: {human-friendly reason}`, not `{SecurityException}: {technical detail}`.

---

### M-4: Pillow Decompression Bomb Protection Not Explicitly Configured

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/thumbnails.py`

The thumbnail generation code uses Pillow's `Image.open()` without configuring `Image.MAX_IMAGE_PIXELS`. Pillow's default limit (178,956,970 pixels) provides some protection, but:

1. A crafted image could consume excessive memory during processing
2. The `ProcessPoolExecutor` spawns multiple workers, multiplying memory usage
3. No explicit pixel limit is set, so behavior depends on Pillow version defaults

**Remediation:**
Explicitly set a pixel limit at module scope:
```python
from PIL import Image
Image.MAX_IMAGE_PIXELS = 200_000_000  # 200MP
```

#### Cross-Review Insights

**Architecture perspective:** Setting `MAX_IMAGE_PIXELS` at module scope in `thumbnails.py` is insufficient if `Image.open()` is ever called elsewhere (e.g., a future image-analysis module). Consider setting it in `__init__.py` or a shared constants module so it applies process-wide.

**AI perspective (amplified risk):** A decompression bomb that expands to a huge pixel count would, if it survived thumbnail generation, also be base64-encoded at full resolution and sent to the vision API via `encode_image()`. A 40,000×40,000 pixel image would produce a ~4.3 GB base64 payload that would fail at the API level but only after consuming enormous memory and bandwidth. Setting `MAX_IMAGE_PIXELS` protects both the thumbnail and AI pipelines simultaneously.

---

### M-5: OpenAI SDK Debug Logging Can Expose API Key

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/ai.py` (absence of logging configuration)

The `openai` SDK uses Python's `logging` module. At `DEBUG` level, the SDK logs HTTP request headers — which include `Authorization: Bearer sk-...`. If a user sets `OPENAI_LOG=debug` or configures the root logger to DEBUG, the API key appears in logs. No code in the project sets logging levels for the `openai` logger.

**Verification:** Confirmed — `ai.py` does not import `logging` or configure any logger levels.

**Remediation:** Add at module scope in `ai.py`:
```python
import logging
logging.getLogger("openai").setLevel(logging.WARNING)
```

This prevents accidental key exposure if library-wide debug logging is enabled.

*This finding was identified by the AI integration specialist during cross-review.*

---

### M-6: Tagger Batch Abort on Single Failure

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/tagger.py:192`

```python
with ThreadPoolExecutor(max_workers=max_workers) as ex:
    futures = [ex.submit(process, item) for item in to_tag]
    for fut in as_completed(futures):
        telemetry = fut.result()  # <-- unguarded, aborts batch on any error
```

The `fut.result()` call has no try/except. If any single image fails (rate limit exhaustion, API error, file I/O error), the entire batch aborts and all successfully generated tags for preceding images are lost — because `save_gallery_items()` is only called after the loop completes (line 211).

**Verification:** Confirmed — `tagger.py` line 192 calls `fut.result()` without exception handling.

This is the same pattern identified in the thumbnail pipeline by the image pipeline reviewer (`thumbnails.py` batch mode). Both should be fixed simultaneously for consistency.

**Remediation:**
```python
errors: list[str] = []
for fut in as_completed(futures):
    try:
        telemetry = fut.result()
        # ... existing telemetry aggregation ...
        updated += 1
    except Exception as exc:
        errors.append(str(exc))
    reporter.advance()
```

*This finding was identified by the AI integration specialist during cross-review.*

---

## Low Findings

### L-1: `subprocess.check_call()` in Bootstrap Without Input Sanitization

**Severity:** Low
**File:** `src/chatgpt_library_archiver/bootstrap.py:68, 117, 135`

```python
subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
# ...
subprocess.check_call(cmd)  # cmd built from discovered executables
# ...
sys.exit(subprocess.call(cmd))
```

The `bootstrap.py` module runs subprocess commands. While `shell=False` is correctly used (list argument), the `cmd` for dependency installation is constructed from discovered paths. The `find_executable()` function searches `PATH` and the venv, but a malicious executable placed in the venv's `bin/` directory could be executed.

**Risk is low** because:
1. The user explicitly invokes `bootstrap`
2. The venv is local to the project
3. No shell expansion occurs

**Remediation:** Consider validating discovered executables against an allowlist of expected names (`pip`, `pip-sync`, `uv`).

---

### L-2: Interactive Credential Prompting Echoes Input

**Severity:** Low
**File:** `src/chatgpt_library_archiver/utils.py:65-72`, `src/chatgpt_library_archiver/tagger.py:37`

```python
# utils.py
val = input(f"{key} = ").strip()

# tagger.py
api_key = input("api_key = ").strip()
```

When users are prompted for credentials interactively, `input()` echoes the text to the terminal. The API key and auth headers will be visible on screen and potentially in terminal scrollback/logs.

**Remediation:**
Use `getpass.getpass()` for sensitive fields:
```python
import getpass
api_key = getpass.getpass("api_key = ").strip()
```

For `auth.txt` header values like `authorization` and `cookie`, consider using `getpass` for those specific keys.

#### Cross-Review Insights

**UX perspective (paste verification concern):** Switching from `input()` to `getpass.getpass()` means users won't see what they're typing. For long bearer tokens and cookies (which are typically pasted, not typed), this is potentially confusing — users can't verify they pasted correctly. The security benefit outweighs this minor UX friction, but add a masked confirmation after accepting the input:

```python
from getpass import getpass
api_key = getpass("api_key = ").strip()
if api_key:
    print(f"  ✓ API key set: {api_key[:8]}...")
```

This gives users confidence their paste worked without exposing the full credential.

---

### L-3: `HttpError.context` Includes URL — May Contain Signed Tokens

**Severity:** Low
**File:** `src/chatgpt_library_archiver/http_client.py:46-53`

```python
@property
def context(self) -> dict[str, object]:
    payload = {"url": self.url, **self.details}
    if self.status_code is not None:
        payload["status_code"] = self.status_code
    return payload
```

Error context includes the full URL, which for ChatGPT API requests includes signed parameters. If errors are logged to a file or external service, these signed URLs could be leaked.

**The status reporter properly displays errors:**

```python
# status.py
message = f"ERROR {message}: {reason}"
```

But the `context` dict may be propagated by callers.

**Remediation:** Strip query parameters from URLs in error context, or redact the `sig` parameter.

#### Cross-Review Insights

**Architecture perspective (interleaving concern):** In the downloader, `tqdm` progress bars and `StatusReporter` log messages can interleave on stderr. If error messages with context dicts (containing URLs with signed tokens) are printed during `tqdm` output, they may be harder for users to notice and could end up in shell scrollback unexpectedly.

---

### L-4: Content-Type Validation Skipped When Header Is Missing

**Severity:** Low
**File:** `src/chatgpt_library_archiver/http_client.py:247-253`

```python
if expected_content_prefixes and content_type:
    lowered = content_type.lower()
    if not any(
        lowered.startswith(prefix.lower())
        for prefix in expected_content_prefixes
    ):
        # ...
```

When `content_type` is `None` (server doesn't send the header), the validation is silently skipped. A server could omit the `Content-Type` header to bypass the image type check and serve arbitrary content.

**Remediation:**
Treat a missing `Content-Type` as a validation failure when `expected_content_prefixes` is specified:
```python
if expected_content_prefixes:
    if not content_type:
        raise HttpError(url=url, reason="Missing Content-Type header", ...)
```

#### Cross-Review Insights

**UX perspective:** The error message "Missing Content-Type header" is opaque to non-developers. Prefer: "Server returned an unexpected response for image X — skipping."

---

### L-5: No Symlink Check on Downloaded/Imported Files

**Severity:** Low
**File:** `src/chatgpt_library_archiver/incremental_downloader.py:97-102`, `src/chatgpt_library_archiver/importer.py:242`

When the downloader writes `temp_path.replace(filepath)` or the importer does `shutil.move(source_path, dest)`, there is no check that the destination isn't a symlink. A symlink at the expected path could cause the tool to overwrite an arbitrary file.

**Risk is low** because:
1. The gallery directory is typically user-controlled
2. The attacker would need write access to the gallery directory
3. The filenames are deterministic (based on image IDs)

**Remediation:**
```python
if filepath.is_symlink():
    raise ValueError(f"Refusing to overwrite symlink: {filepath}")
```

---

### L-6: Base64-Encoded Images Persist in Process Memory

**Severity:** Low
**File:** `src/chatgpt_library_archiver/ai.py:101-107`

The `encode_image()` function loads the entire file into memory and base64-encodes it. For a batch of 500 images at 10 MB each, this creates ~13.3 MB base64 strings per concurrent worker. If the process crashes or produces a core dump, those base64 payloads (containing user images from a private ChatGPT library) persist in the dump.

This is primarily a resource concern, but it has a privacy dimension given the nature of the images (personal AI-generated content). The risk is low for a CLI tool — core dumps are not generated by default on most systems — but is worth documenting for users running in environments where core dumps are enabled.

**Remediation:** No immediate code change required. Document the memory behavior. The recommended image-resize optimization (pre-encoding resize to 1024px) would reduce memory footprint as a side effect.

*This finding was identified by the AI integration specialist during cross-review.*

---

## Informational Findings

### I-1: Dependency Versions — No Known CVEs (as of audit date)

**Severity:** Informational

Installed versions reviewed:

| Package | Version | Status |
|---------|---------|--------|
| `requests` | 2.32.3 | ✅ Current |
| `urllib3` | 2.2.3 | ✅ Current |
| `certifi` | 2024.8.30 | ⚠️ May want to update — CA bundle date is 8 months old |
| `cryptography` | 43.0.0 | ✅ No known CVEs |
| `openai` | 2.24.0 | ✅ Current |
| `Pillow` | 12.1.1 | ✅ Current |
| `tqdm` | 4.66.5 | ✅ Current |

**Note:** `pyproject.toml` specifies minimum versions only (`>=`) with no upper bounds. This is intentional for a library/tool but means future installs could pick up breaking changes or vulnerable versions.

**Recommendation:** Consider using a pinned lock file (`requirements.txt` with exact versions) for reproducible builds. The current `requirements.txt` uses `>=` constraints.

---

### I-2: `auth.txt` Was Previously Committed to Git (Template Content Only)

**Severity:** Informational

Git history shows `auth.txt` was committed in `17a4b3a` and later untracked in `75f1fb3`. Review of the committed content shows it was **template/placeholder content** (e.g., `<your_token_here>`), not actual credentials.

```
$ git show 17a4b3a:auth.txt | head -2
url=https://chatgpt.com/backend-api/my/recent/image_gen?limit=100
authorization=Bearer <your authorization token here>
```

**No credential leak occurred**, but this pattern (commit then untrack) is fragile. The `auth.txt.example` file now serves as the template.

---

### I-3: `browser_extract.py` Uses Secure Subprocess Patterns

**Severity:** Informational (Positive Finding)

The `browser_extract.py` module:
- ✅ Uses list-form subprocess calls (no `shell=True`)
- ✅ Uses hardcoded command arguments (`security`, `find-generic-password`, `-s`, `-w`)
- ✅ Does not interpolate user input into commands
- ✅ Uses `capture_output=True` to prevent command output from leaking
- ✅ Disables redirects when exchanging cookies for tokens (`allow_redirects=False`)
- ✅ Copies cookie DB to temp dir to avoid locking issues
- ✅ Sets `0o600` on the temporary database copy

```python
result = subprocess.run(
    ["security", "find-generic-password", "-s", service, "-w"],
    capture_output=True, text=True, check=True,
)
```

---

### I-4: Credential Masking Is Implemented Correctly

**Severity:** Informational (Positive Finding)

The `_mask()` function in `browser_extract.py` provides credential masking:

```python
def _mask(value: str, visible: int = 8) -> str:
    if len(value) <= visible:
        return "***"
    return value[:visible] + "..."
```

This is used in the `extract-auth --dry-run` command to display masked credentials:

```python
_SENSITIVE_KEYS = {"authorization", "cookie"}
for key, value in config.items():
    display = _mask(value) if key in _SENSITIVE_KEYS else value
```

The OAI device ID and client version are **not** masked, which is acceptable as they are not sensitive.

---

## Audit Checklist Results

### Credentials
- [x] `auth.txt` is in `.gitignore`
- [x] `tagging_config.json` is in `.gitignore`
- [x] File permissions set appropriately on `auth.txt` — **`600`** ✅
- [ ] **File permissions set appropriately on `tagging_config.json`** — **`644` ❌ (C-1)**
- [x] Credentials never logged or included in error messages (verified: no `print(token)` patterns)
- [ ] **OpenAI SDK logger not suppressed** — could expose API key at DEBUG level ❌ (M-5)
- [x] Credentials never written to `metadata.json` (verified: `to_dict()` does not include auth data)
- [x] Environment variable fallbacks work correctly — ✅ Verified: `resolve_config()` checks three env vars

### Downloads
- [ ] **Content-type validated before saving** — Partial ✅ / ❌ bypassed when header missing (L-4)
- [ ] **File paths sanitized (no `../` traversal)** — ❌ Not validated (M-3)
- [x] Checksums verified after download — `stream_download()` supports `expected_checksum`
- [ ] **Reasonable size limits enforced** — ❌ No limits (H-3)
- [ ] **Redirects don't leak credentials to other domains** — ❌ Not protected in main client (H-2)

### Gallery
- [ ] **HTML output escaped** — ❌ Uses `innerHTML` with unescaped values (H-1)

### AI Integration
- [ ] **AI-generated tags sanitized before storage** — ❌ Tags from API stored verbatim (H-1 chain)
- [ ] **Batch failure isolation** — ❌ Single failure aborts entire tagging batch (M-6)
- [ ] **SDK logging suppressed** — ❌ No logging configuration (M-5)

### Dependencies
- [x] No known CVEs in current installed versions
- [x] `requests` session uses default safe TLS settings (no `verify=False`)
- [x] Pillow image parsing handles common errors (`UnidentifiedImageError`, `OSError`)

---

## Recommendations Priority

### Immediate (Before Next Release)
1. **Rotate the exposed API key** in `tagging_config.json` (C-1)
2. **Fix `tagging_config.json` file permissions** to `0o600` — extract `write_secure_file()` helper (C-1)
3. **Escape HTML in gallery viewer** — prefer full `createElement()`/`textContent` refactor (H-1)
4. **Add download size limit** as a parameter on `stream_download()` (H-3)
5. **Implement atomic metadata writes** via `tempfile` + `os.replace()` (H-4)

### Short-Term (Next Sprint)
6. **Strip/avoid forwarding auth headers on redirects** — separate `get_json()` (no redirects) from `stream_download()` (strip on cross-origin) (H-2)
7. **Validate downloaded filenames** — sanitize + verify path (M-3)
8. **Suppress OpenAI SDK logger** to WARNING level (M-5)
9. **Fix tagger batch failure isolation** — try/except around `fut.result()` (M-6)
10. **Strip HTML-like content from AI-generated tags** before persisting (defense in depth for H-1)
11. **Use `getpass`** for sensitive interactive prompts with masked confirmation (L-2)
12. **Set explicit Pillow pixel limit** process-wide (M-4)

### Long-Term
13. **Hash API keys** for cache keys (M-1)
14. **Strip signed URLs** from persisted metadata (M-2)
15. **Add Content-Type requirement** when validation is requested (L-4)
16. **Add symlink checks** before file writes (L-5)
17. **Pin dependency versions** in a lock file (I-1)

---

## Cross-Review Contributors

The following reviewers provided additional perspectives that were incorporated into this audit:

| Reviewer | Perspective | Key Contributions |
|----------|-------------|-------------------|
| **Architecture & Code Quality** | Architectural soundness of remediations | Centralized `write_secure_file()` helper, DOM construction over `escapeHtml()`, separated redirect strategies for API vs CDN, strengthened M-5→H-4 upgrade argument, identified thread safety gap in `_CLIENT_CACHE` |
| **Gallery UX Designer** | User-facing security impact | Error message usability patterns, `getpass` paste verification UX, `file://` protocol edge cases for `safeHref()`, `conversation_link` display when sanitized to `#`, metadata corruption UX impact |
| **OpenAI Integration Specialist** | AI-specific security concerns | SDK debug logging key exposure (M-5), base64 memory/core dump risk (L-6), API→tags→innerHTML chained XSS vector, tagger batch abort data loss (M-6), API key scope analysis for C-1 |

**Source documents:**
- `docs/reviews/cross-review-architecture-perspective.md`
- `docs/reviews/cross-review-ux-perspective.md`
- `docs/reviews/cross-review-ai-perspective.md`

---

## Methodology

This audit involved:
1. Manual line-by-line review of all Python source files in `src/chatgpt_library_archiver/` and `src/chatgpt_library_archiver/cli/commands/`
2. Review of the bundled HTML/JavaScript gallery template (`gallery_index.html`)
3. Inspection of configuration files (`auth.txt`, `auth.txt.example`, `tagging_config.json`)
4. File permission verification via `stat`
5. Git history analysis for credential leaks
6. Dependency version auditing via `pip list`
7. Pattern-based code search for known anti-patterns (`verify=False`, `shell=True`, `innerHTML`, credential logging)
8. Review of `.gitignore` coverage
9. Cross-review integration: critical evaluation and source-code verification of findings from Architecture, UX, and AI specialist reviewers
