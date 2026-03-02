# HTTP Resilience & Error Handling Review

**Date**: 2026-03-01
**Scope**: `http_client.py`, `incremental_downloader.py`, `status.py`, `test_http_client.py`, `test_end_to_end.py`
**Reference**: `.github/skills/http-resilience/SKILL.md`

---

## Executive Summary

The HTTP layer is **well-architected** overall. The `HttpClient` class provides a clean, testable abstraction with streaming downloads, checksum validation, structured errors, and thread-safe session management. However, several gaps exist relative to the http-resilience skill patterns, primarily around **redirect credential safety**, **rate-limit awareness**, **timeout granularity**, and **download size limits**. The test suite covers happy paths and key error branches but lacks coverage for retry behavior, concurrent download coordination, and network-level failure modes.

### Risk Summary

| Area | Risk Level | Notes |
|------|-----------|-------|
| Redirect credential leak | **High** | All custom headers (auth, cookies, oai-* identifiers) forwarded on cross-domain redirects |
| No download size limit | **Medium** | Disk exhaustion possible from malicious/huge responses |
| No Retry-After support | **Medium** | Aggressive retry after 429 may trigger bans |
| Single timeout value | **Low** | Connect and read share a 30s timeout |
| Hardcoded concurrency | **Low** | 14 workers not configurable |

---

## 1. Retry Strategy

### Current Implementation

```python
# http_client.py:65-74
Retry(
    total=retries,          # default 3
    connect=retries,
    read=retries,
    backoff_factor=0.5,     # 0.5s, 1s, 2s
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=("GET", "HEAD"),
    raise_on_status=False,
)
```

### Skill Specification

```python
Retry(
    total=3,
    backoff_factor=1.0,     # 1s, 2s, 4s
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "HEAD"],
    raise_on_status=False,
)
```

### Drift Analysis

| Parameter | Skill | Actual | Impact |
|-----------|-------|--------|--------|
| `backoff_factor` | `1.0` | `0.5` | Retries happen 2× faster — may be too aggressive for 429 |
| `connect` / `read` | not set | `retries` | Explicit retry counts per failure mode — **stricter** than skill |
| Jitter | not mentioned | not implemented | urllib3 ≥1.26 adds ±0.5s jitter by default via `backoff_jitter`, but this isn't explicitly configured |

### Assessment

The retry configuration is **good** but slightly more aggressive than recommended. The faster backoff is mostly harmless for 5xx errors but may cause problems with 429 (rate limiting), where the server expects the client to slow down. The explicit `connect` and `read` retry counts are a positive deviation — they prevent the retry budget from being consumed entirely by one failure mode.

**No test covers retry behavior.** The `FakeSession` in tests doesn't simulate retry sequences.

### Recommendations

1. **P2**: Increase `backoff_factor` to `1.0` to match skill and be more respectful of server rate limits.
2. **P3**: Add a test that verifies retry is configured (inspect the adapter's `max_retries` attribute).

---

## 2. Streaming Downloads

### Current Implementation

`stream_download()` in [http_client.py](src/chatgpt_library_archiver/http_client.py#L176-L249):

- Uses `stream=True` on `session.get()` ✓
- 64KB chunk size (vs 8KB in skill) — reasonable, reduces syscall overhead ✓
- SHA-256 computed inline during streaming ✓
- Empty chunks filtered (`if not chunk: continue`) ✓
- Parent directory auto-created (`mkdir(parents=True, exist_ok=True)`) ✓
- Partial file cleanup on exception ✓

The downloader in [incremental_downloader.py](src/chatgpt_library_archiver/incremental_downloader.py#L91-L113) adds:

- Temp file pattern (`{id}.download`) renamed on success ✓
- Content-type → extension mapping via `mimetypes.guess_extension()` ✓

### Gaps

- **No resumable downloads**: If a download fails mid-stream, the entire file is re-downloaded. There is no `Range` header support for partial recovery.
- **No per-file progress**: Download progress is only tracked at the item level (items completed), not bytes-within-file. For large images (10MB+), download of individual files provides no feedback.
- **No Content-Length validation**: The `Content-Length` header is never compared against actual bytes received.

### Recommendations

1. **P3**: Consider logging a warning when `bytes_downloaded` differs from `Content-Length` (if present) — catches truncated responses silently accepted by the server.
2. **P4**: Per-file byte-level progress is a nice-to-have for UX but not critical given typical image sizes.

---

## 3. Timeout Configuration

### Current Implementation

```python
# http_client.py:83
self.timeout = timeout  # default 30.0

# Used as:
response = session.get(url, headers=headers, timeout=self.timeout)
```

A single float passed to `requests.get()` sets **both** connect and read timeouts to the same value. The skill states "Configurable timeouts (connect + read)" implying they should be separate.

### Assessment

A 30-second combined timeout is reasonable for image downloads but suboptimal:

- **Connect timeout** should be short (5–10s) — if the server isn't reachable, fail fast.
- **Read timeout** should be longer (30–60s) — large files over slow connections need time.

Using a single value means either connect failures take too long to detect, or reads of large files may time out prematurely.

### Recommendation

1. **P2**: Split into a `(connect_timeout, read_timeout)` tuple. The `requests` library accepts `timeout=(connect, read)` natively:

```python
def __init__(self, *, connect_timeout: float = 10.0, read_timeout: float = 60.0, ...):
    self.timeout = (connect_timeout, read_timeout)
```

---

## 4. Error Classification

### Current Implementation

`HttpError` is a well-designed structured exception:

```python
class HttpError(RuntimeError):
    url: str
    status_code: int | None
    reason: str
    details: dict[str, object]
    response: Response | None
```

The downloader classifies errors correctly:

| Scenario | Handling | Correct? |
|----------|----------|----------|
| 401/403 from API | Prompt for re-auth or re-extract from browser | ✓ |
| Other HTTP errors | Log and break pagination loop | ✓ |
| Missing URL on item | `ValueError` caught in `download_image` | ✓ |
| Empty response | `HttpError("Empty response body")` | ✓ |
| Checksum mismatch | `HttpError("Checksum mismatch")` | ✓ |
| Content-type mismatch | `HttpError("Unexpected content type")` | ✓ |

### Gap

The downloader's `download_image` function catches all exceptions and returns `("error", ...)` — this means **transient errors are not retried at the application level**. urllib3 retries handle transport-layer failures, but a single 500 response that exhausts retries results in the item being permanently skipped in that run.

### Recommendation

1. **P3**: Consider adding application-level retry for individual failed downloads (e.g., collect failures and retry once at the end of the run), separate from the urllib3 transport-level retry.

---

## 5. Redirect Handling

### Current Implementation

There is **no explicit redirect handling**. The code relies entirely on `requests` default behavior, which automatically follows up to 30 redirects.

### Security Concern — Credential & Header Forwarding

The skill explicitly warns:

> Bearer tokens and cookies are sent with every request — ensure redirects don't leak them to third-party domains.

The `incremental_downloader.py` `build_headers()` function sends **eight headers** on every request:

```python
headers = {
    "Authorization": config["authorization"],
    "Cookie": config["cookie"],
    "User-Agent": config["user_agent"],
    "Accept": "application/json",
    "Referer": config["referer"],
    "oai-client-version": config["oai_client_version"],
    "oai-device-id": config["oai_device_id"],
    "oai-language": config["oai_language"],
}
```

When `requests` follows a redirect (e.g., from `chatgpt.com` to a CDN like `oaidalleapiprodscus.blob.core.windows.net`), **all of these headers are forwarded to the redirect target**. This is the default `requests` behavior.

While ChatGPT's CDN is first-party infrastructure, the authorization header contains a bearer token that should not be sent to arbitrary domains. A server-side misconfiguration or open redirect could leak credentials.

#### Severity breakdown by header

| Header | Sensitivity | Risk on leak |
| -------- | ------------ | -------- |
| `Authorization` | **High** | Bearer JWT — session impersonation |
| `Cookie` | **High** | Session token — potentially longer-lived than the JWT; accepted by any `chatgpt.com` subdomain |
| `oai-device-id` | **Medium** | Persistent device identifier — correlatable to user's ChatGPT account |
| `oai-client-version` | **Low** | Fingerprinting — reveals tool version |
| `oai-language` | **Low** | Fingerprinting — reveals locale |
| `Referer` | **Low** | Reveals that the request originates from the library tool |
| `User-Agent` / `Accept` | **Minimal** | Standard HTTP headers, expected on any request |

The original version of this review identified only `Authorization` and `Cookie` as at-risk headers. The security cross-review correctly observes that the `oai-device-id` and other ChatGPT-specific headers also create a fingerprintable profile that could be correlated to the user's session if logged by a redirect target.

#### Both request paths are affected

This vulnerability applies to **both** HTTP methods on `HttpClient`:

- `stream_download()` — image downloads, where CDN redirects are most likely
- `get_json()` — API metadata fetches, where API version migrations or load balancer redirects could occur

The `browser_extract.py` module already uses `allow_redirects=False` for its token-exchange flows, showing awareness of this risk exists in the codebase but was not applied uniformly.

#### Origin comparison must include scheme and port

The original version of this review compared only hostnames. The security cross-review correctly notes that a **full origin comparison** (scheme + host + port) is necessary to also catch HTTPS→HTTP downgrades, which would transmit credentials in plaintext.

> **Implementation note:** `urlparse()` returns `port=None` for URLs without an explicit port (e.g., `https://example.com`). This means `https://example.com` and `https://example.com:443` would be treated as different origins by a naive tuple comparison. In practice, all ChatGPT API and CDN URLs use standard ports without explicit specification, so this edge case is unlikely to cause false positives. A production-hardened version could normalize default ports (443 for HTTPS, 80 for HTTP), but this is not critical for the current use case.

### Recommendation

1. **P1**: Strip all sensitive and ChatGPT-specific headers on cross-origin redirects. Override `Session.rebuild_auth()` to compare full origins:

   ```python
   from urllib.parse import urlparse

   class SafeSession(Session):
       """Session that strips sensitive headers on cross-origin redirects."""

       _SENSITIVE_HEADERS = frozenset({
           "Authorization", "Cookie",
           "oai-client-version", "oai-device-id", "oai-language",
           "Referer",
       })

       def rebuild_auth(self, prepared_request, response):
           original = urlparse(response.request.url)
           redirect = urlparse(prepared_request.url)
           original_origin = (original.scheme, original.hostname, original.port)
           redirect_origin = (redirect.scheme, redirect.hostname, redirect.port)

           if original_origin != redirect_origin:
               for header in self._SENSITIVE_HEADERS:
                   prepared_request.headers.pop(header, None)
           else:
               super().rebuild_auth(prepared_request, response)
   ```

   Key properties of this fix vs. the original hostname-only approach:
   - Strips **all** custom/sensitive headers, not just `Authorization` and `Cookie`
   - Compares full origin (scheme + host + port), catching HTTPS→HTTP downgrades
   - Uses `frozenset` for O(1) lookup and immutability
   - `Referer` is included because it reveals tool usage to third parties
   - `User-Agent` and `Accept` are left intact as standard HTTP headers

2. **P2**: Set `session.max_redirects = 5` — the default of 30 is excessive for image downloads and API calls.

---

## 6. Content Validation

### Current Implementation

| Check | Implemented | Location |
|-------|------------|----------|
| Content-Type prefix validation | ✓ | `stream_download()` via `expected_content_prefixes` |
| Non-empty body validation | ✓ | `stream_download()` via `allow_empty` flag |
| SHA-256 checksum computation | ✓ | `stream_download()` always computes |
| Checksum verification | ✓ | `stream_download()` via `expected_checksum` |
| Extension from Content-Type | ✓ | `download_image()` in downloader |
| JSON response validation | ✓ | `get_json()` checks Content-Type and decodes |
| JSON structure validation | ✓ | `get_json()` rejects non-Mapping responses |
| Maximum download size | ✗ | Not implemented |
| Content-Length vs actual | ✗ | Not compared |

### Assessment

Content validation is **strong**. The checksum and content-type prefixes are well-implemented, and the downloader correctly derives file extensions from the response Content-Type rather than trusting the URL.

### Recommendations

1. **P2**: Add a `max_bytes` parameter to `stream_download()` that raises `HttpError` if the download exceeds a configurable limit (e.g., 100MB). This prevents disk exhaustion from abnormally large responses.

   ```python
   if max_bytes and bytes_downloaded > max_bytes:
       destination.unlink(missing_ok=True)
       raise HttpError(url=url, reason="Download exceeded size limit", ...)
   ```

2. **P4**: Log a warning when `Content-Length` is present and doesn't match `bytes_downloaded`.

---

## 7. Connection Management

### Current Implementation

```python
# Thread-local sessions
self._local = threading.local()

def _get_session(self) -> Session:
    session = getattr(self._local, "session", None)
    if session is None:
        session = self._create_session()
        self._local.session = session
    return session
```

- Each thread gets its own `Session` (thread-local storage) ✓
- All sessions tracked in `_sessions` set with lock for cleanup ✓
- Context manager protocol (`__enter__`/`__exit__`) for resource cleanup ✓
- `HTTPAdapter` mounted for both `http://` and `https://` ✓

### Assessment

This is **excellent** — one of the strongest parts of the implementation. Thread-local sessions avoid the thread-safety issues that plague shared `Session` objects, while the tracked set ensures all sessions are closed on shutdown.

### Minor Gap

The `HTTPAdapter` uses urllib3 defaults for connection pool size (`pool_connections=10`, `pool_maxsize=10`). With 14 concurrent download workers, each thread has its own session with its own pool, so this isn't a bottleneck — but it means up to 14 × 10 = 140 potential connections. This is fine in practice but worth documenting.

---

## 8. Rate Limiting

### Current Implementation

- **429 in retry list**: urllib3 retries on 429 with backoff ✓
- **Inter-page delay**: `time.sleep(0.5)` between API pagination calls ✓
- **No `Retry-After` header parsing**: urllib3's `Retry` does support `respect_retry_after_header=True` (default), but only when the retry is triggered by a status code in `status_forcelist`. The `backoff_factor` takes precedence if `Retry-After` is shorter.

### Assessment

Basic rate-limit handling is present via urllib3 retry, but the implementation doesn't distinguish between "server is overloaded" (429) and "server had a transient error" (503). For 429 specifically, the server often provides a `Retry-After` header indicating the minimum wait — the current 0.5s backoff factor may be shorter than what the server requests.

urllib3's `Retry` class does respect `Retry-After` headers by default, but only as a **minimum** — if the calculated backoff is longer, it uses that instead. This is reasonable behavior.

### Recommendations

1. **P2**: Consider adding `retry_after_header=True` explicitly to Retry configuration to make the intent clear (it's the default, but being explicit aids readability).
2. **P3**: Make the inter-page sleep configurable rather than hardcoded at 0.5s.

---

## 9. Network Resilience

### Current Implementation

| Scenario | Handling |
|----------|----------|
| Connection refused | urllib3 retry (up to 3 attempts) |
| DNS resolution failure | urllib3 retry |
| Connection reset mid-download | Exception caught, partial file cleaned up |
| Read timeout | urllib3 retry |
| SSL certificate error | Not caught — propagates as `SSLError` |
| Malformed response | `response.iter_content()` raises, caught by `except Exception` |

### Assessment

Network resilience is **adequate** for the use case. urllib3 retries handle the most common transient failures. The cleanup of partial downloads (`destination.unlink()` in the `except` block) is correct.

### Gap

When `stream_download()` encounters an exception during `iter_content()`, it cleans up the file and re-raises. However, the `response.close()` in the `finally` block runs after the `except` block — this is correct but could be clearer. The current structure:

```python
try:
    with destination.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=chunk_size):
            ...
except Exception:
    if destination.exists():
        destination.unlink()
    response.close()
    raise
finally:
    response.close()
```

Note that `response.close()` is called **twice** on error (once in `except`, once in `finally`). This is harmless (closing an already-closed response is a no-op) but indicates minor structural imprecision.

### Recommendation

1. **P4**: Remove the `response.close()` from the `except` block since `finally` handles it unconditionally.

---

## 10. Progress Reporting

### Current Implementation

`StatusReporter` in [status.py](src/chatgpt_library_archiver/status.py):

- tqdm-backed progress bar with dynamic total ✓
- `log()` writes above the bar via `tqdm.write()` ✓
- Structured error collection (`StatusError` dataclass) ✓
- Dynamic total incrementing (`add_total()`) for paginated downloads ✓
- Auto-disable when not a TTY ✓

The downloader uses a **two-bar layout**:
- `position=0`: Per-page download progress (inner `tqdm` in `ThreadPoolExecutor.map`)
- `position=1`: Overall progress via `StatusReporter`

### Assessment

Progress reporting is **well-implemented** for the use case. The structured error collection is a standout — errors are both displayed immediately and accumulated for potential summary reporting.

### Minor Issues

- The inner `tqdm` bar (per-page) and outer `StatusReporter` bar overlap in purpose — both show image counts. This may be confusing when many pages are processed.
- No byte-level download progress for individual files (only item completion counts).
- The `bar_format` on the inner tqdm omits ETA and speed, which could be useful.

---

## 11. Concurrent Downloads

### Current Implementation

```python
max_workers = 14

with ThreadPoolExecutor(max_workers=max_workers) as executor:
    results = list(
        tqdm(
            executor.map(download_image, metas),
            ...
        )
    )
```

- 14 concurrent workers, hardcoded ✓
- Thread-local sessions prevent cross-thread session sharing ✓
- New `ThreadPoolExecutor` created per page of results ✓

### Assessment

The concurrency model is **functional** but has several concerns:

1. **14 workers is aggressive** and not configurable. This could overwhelm the server or trigger rate limiting. A more conservative default (4–6) with a CLI option would be better.

2. **New ThreadPoolExecutor per page**: Each page of results creates and tears down a thread pool. This wastes thread creation overhead. A single pool for the entire download session would be more efficient.

3. **No per-second rate limiting**: There's no mechanism to limit requests-per-second beyond the fixed worker count. If images are small, 14 workers could generate bursts of requests.

### Recommendations

1. **P2**: Make `max_workers` configurable via CLI argument with a lower default (e.g., 6).
2. **P3**: Move the `ThreadPoolExecutor` to the outer scope (one pool for the entire download session).
3. **P4**: Consider a `time.sleep()` per worker or a semaphore-based rate limiter for burst protection.

---

## 12. Alignment with Skill — Drift Summary

| Skill Pattern | Implementation Status | Drift |
|---------------|----------------------|-------|
| `Retry(total=3)` | ✓ Default `retries=3` | None |
| `backoff_factor=1.0` | ⚠ `0.5` — faster than recommended | Minor |
| `status_forcelist=[429, 500, 502, 503, 504]` | ✓ Exact match | None |
| `allowed_methods=["GET", "HEAD"]` | ✓ Tuple instead of list, equivalent | None |
| `raise_on_status=False` | ✓ | None |
| Streaming with checksum | ✓ Well-implemented | None |
| `chunk_size=8192` | ⚠ `64KB` — larger but better performance | Positive |
| Structured `HttpError` | ✓ Matches skill spec exactly | None |
| Content-Type validation | ✓ Via `expected_content_prefixes` | None |
| Non-empty body check | ✓ Via `allow_empty` flag | None |
| SHA-256 checksum | ✓ Computed inline | None |
| Credential redirect safety | ✗ Not implemented | **Significant** |
| Size limits | ✗ Not implemented | Notable |
| TLS verification | ✓ Never disabled (no `verify=False`) | None |
| Path sanitization | ✓ IDs used as filenames, not user input | None |
| Mock `requests.Session` | ✓ `FakeSession` in tests | None |
| Test retry behavior | ✗ No retry tests | Gap |
| Test streaming checksum | ✓ `test_stream_download_writes_file` | None |
| Test error scenarios | ✓ 500, bad content-type, empty, non-mapping JSON | None |

---

## 13. Test Coverage Assessment

### What's Tested

| Scenario | Test |
|----------|------|
| JSON fetch success | `test_get_json_success` |
| JSON invalid content-type | `test_get_json_invalid_content_type` |
| JSON rejects non-mapping | `test_get_json_rejects_non_mapping` |
| Response close on error | `test_get_json_closes_response_on_error` |
| Stream download writes file | `test_stream_download_writes_file` |
| Content-type prefix validation | `test_stream_download_validates_content_prefix` |
| Checksum mismatch | `test_stream_download_checksum_mismatch` |
| Empty payload allowed | `test_stream_download_allows_empty_payload` |
| Session cleanup | `test_http_client_close_releases_sessions` |
| End-to-end download flow | `test_incremental_download_and_gallery` |
| Browser auth path | `test_incremental_download_with_browser_calls_extract_auth` |

### What's Not Tested

| Gap | Risk |
|-----|------|
| Retry behavior (status codes in forcelist) | Medium — configuration correctness unverified |
| HTTP 429 handling in downloader | Medium — rate limit path untested |
| Concurrent download behavior | Medium — thread safety untested |
| Partial download cleanup on network error | Low — cleanup logic exists but untested |
| Empty response rejection (default `allow_empty=False`) | Low — happy-path covered |
| `get_json` with `expected_content_types` parameter | Low — parameter exists but untested |
| 401/403 re-auth loop in downloader | Medium — critical path untested |
| Thread-local session isolation | Low — architecture is sound |

---

## Prioritized Recommendations

### P1 — Security

1. **Strip all sensitive headers on cross-origin redirects**: Override `Session.rebuild_auth()` to compare full origins (scheme + host + port) and remove `Authorization`, `Cookie`, `oai-device-id`, `oai-client-version`, `oai-language`, and `Referer` headers when a redirect crosses origins. This prevents token leakage and fingerprinting if ChatGPT's API or CDN redirects to an unexpected domain, and protects against HTTPS→HTTP credential exposure. Both `get_json()` and `stream_download()` are affected.

### P2 — Correctness & Robustness

2. **Increase `backoff_factor` to `1.0`**: Aligns with skill recommendation and provides more polite retry behavior, especially for 429 responses.

3. **Split timeout into `(connect_timeout, read_timeout)` tuple**: Use `(10.0, 60.0)` to fail fast on unreachable servers while allowing large file reads to complete.

4. **Add `max_bytes` to `stream_download()`**: Enforce a configurable maximum download size to prevent disk exhaustion from abnormally large responses.

5. **Make `max_workers` configurable**: Expose via CLI with a default of 6 instead of hardcoded 14.

### P3 — Reliability

6. **Add retry behavior tests**: Verify that the `Retry` configuration on `HTTPAdapter` matches expectations (inspect adapter attributes in test).

7. **Test the 401/403 re-auth path**: The downloader has a code path for re-prompting credentials. Add an end-to-end test that simulates auth expiry mid-pagination.

8. **Application-level retry for failed downloads**: Collect failed items and retry them once at the end of the run, separate from urllib3 transport retries.

9. **Make inter-page sleep configurable**: Replace hardcoded `time.sleep(0.5)` with a parameter.

### P4 — Polish

10. **Remove duplicate `response.close()` in `stream_download()`**: The `except` block calls `response.close()` unnecessarily since `finally` handles it.

11. **Log Content-Length mismatch**: Warn when the declared Content-Length doesn't match actual bytes downloaded.

12. **Use a single `ThreadPoolExecutor` for the entire session**: Avoid per-page pool creation overhead.

13. **Add `respect_retry_after_header=True` explicitly**: Although it's the default, explicit is better than implicit for documentation purposes.

---

## Cross-Review Contributors

This review was enhanced with findings from the following cross-review:

| Reviewer | Report | Contributions |
|----------|--------|---------------|
| Security Auditor | [cross-review-security-perspective.md](cross-review-security-perspective.md) §2 | Identified that **all** custom headers (not just `Authorization`/`Cookie`) leak on redirects; enhanced `rebuild_auth()` fix to compare full origins (scheme+host+port) and strip `oai-*` identifiers; noted that `get_json()` is equally affected; flagged that missing download size limits compound with credential forwarding risk |

### Findings evaluated but adjusted

- The cross-review's enhanced `SafeSession` code omitted `Referer` from `_SENSITIVE_HEADERS`. This review adds it, since `Referer: https://chat.openai.com/library` reveals tool usage to third-party redirect targets.
- The cross-review notes that `User-Agent` and `oai-*` values "create a fingerprint" — this is accurate but the practical risk depends on the redirect target logging headers, which is common for CDNs. The `oai-device-id` is the most identifying of the custom headers; `oai-client-version` and `oai-language` carry lower individual risk but are stripped as defense-in-depth.
- The cross-review's observation that the backoff factor discussion is "overrated for security" (§2.3.1) is fair — the space allocated to Section 1 reflects its relevance as a *reliability* concern, not a security one. No changes were made to Section 1 as a result.
