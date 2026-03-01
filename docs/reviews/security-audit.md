# Security Audit Report — chatgpt-library-archiver

**Audit Date:** 2026-03-01
**Auditor:** Security Auditor (automated)
**Scope:** Full codebase review of `src/chatgpt_library_archiver/` and supporting configuration files
**Commit Range:** Current working tree (HEAD)

---

## Executive Summary

The chatgpt-library-archiver is a local CLI tool that handles sensitive authentication tokens (ChatGPT Bearer tokens, session cookies) and OpenAI API keys. Overall, the project demonstrates **good security awareness** — credentials are masked in output, file permissions are considered, `.gitignore` covers sensitive files, and TLS verification is never disabled.

However, several issues were identified ranging from **Critical** (live credentials committed to files, API key stored world-readable) to **Medium** (XSS via `innerHTML`, missing redirect credential stripping, no download size limits) to **Low/Informational** (API key used as dictionary key in memory, signed URLs persisted in metadata).

### Severity Summary

| Severity | Count |
|----------|-------|
| **Critical** | 2 |
| **High** | 3 |
| **Medium** | 5 |
| **Low** | 5 |
| **Informational** | 4 |

---

## Critical Findings

### C-1: Live OpenAI API Key in `tagging_config.json` with World-Readable Permissions

**Severity:** Critical
**File:** `tagging_config.json` (project root)

The `tagging_config.json` file contains a **real OpenAI API key** and has permissions `644` (owner read/write, group read, world read):

```json
{
  "api_key": "sk-REDACTED",
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
# src/chatgpt_library_archiver/tagger.py:29-31
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
1. Configure `requests.Session` to not send auth headers on cross-domain redirects. The `requests` library (since 2.32.0+) has `session.trust_env` and redirect hooks, but the most reliable approach is:
   ```python
   # In HttpClient, override session to strip sensitive headers on domain change
   session.max_redirects = 5  # Limit redirect chains
   ```
2. Or set `allow_redirects=False` and handle redirects manually, stripping `Authorization` and `Cookie` headers if the redirect target is a different origin.

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

---

## Medium Findings

### M-1: API Key Used as Dictionary Key in Memory Cache

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/ai.py:23-28`

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

---

### M-5: `metadata.json` Written Without Atomic Replacement

**Severity:** Medium
**File:** `src/chatgpt_library_archiver/metadata.py:175-179`

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
**File:** `src/chatgpt_library_archiver/utils.py:65-72`, `src/chatgpt_library_archiver/tagger.py:24`

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

---

### L-4: Content-Type Validation Skipped When Header Is Missing

**Severity:** Low
**File:** `src/chatgpt_library_archiver/http_client.py:212-219`

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
- [x] Credentials never written to `metadata.json` (verified: `to_dict()` does not include auth data)
- [ ] **Environment variable fallbacks work correctly** — ✅ Verified: `resolve_config()` checks three env vars

### Downloads
- [ ] **Content-type validated before saving** — Partial ✅ / ❌ bypassed when header missing (L-4)
- [ ] **File paths sanitized (no `../` traversal)** — ❌ Not validated (M-3)
- [x] Checksums verified after download — `stream_download()` supports `expected_checksum`
- [ ] **Reasonable size limits enforced** — ❌ No limits (H-3)
- [ ] **Redirects don't leak credentials to other domains** — ❌ Not protected in main client (H-2)

### Gallery
- [ ] **HTML output escaped** — ❌ Uses `innerHTML` with unescaped values (H-1)

### Dependencies
- [x] No known CVEs in current installed versions
- [x] `requests` session uses default safe TLS settings (no `verify=False`)
- [x] Pillow image parsing handles common errors (`UnidentifiedImageError`, `OSError`)

---

## Recommendations Priority

### Immediate (Before Next Release)
1. **Rotate the exposed API key** in `tagging_config.json` (C-1)
2. **Fix `tagging_config.json` file permissions** to `0o600` (C-1)
3. **Escape HTML in gallery viewer** to prevent XSS (H-1)
4. **Add download size limit** (H-3)

### Short-Term (Next Sprint)
5. **Strip/avoid forwarding auth headers on redirects** (H-2)
6. **Validate downloaded filenames** against path traversal (M-3)
7. **Use `getpass`** for sensitive interactive prompts (L-2)
8. **Set explicit Pillow pixel limit** (M-4)
9. **Implement atomic metadata writes** (M-5)

### Long-Term
10. **Hash API keys** for cache keys (M-1)
11. **Strip signed URLs** from persisted metadata (M-2)
12. **Add Content-Type requirement** when validation is requested (L-4)
13. **Add symlink checks** before file writes (L-5)
14. **Pin dependency versions** in a lock file (I-1)

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
