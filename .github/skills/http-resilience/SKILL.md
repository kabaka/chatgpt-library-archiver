---
name: http-resilience
description: HTTP client resilience patterns for the archiver — retry with exponential backoff, streaming downloads with checksum validation, content-type verification, and structured error handling using requests and urllib3
---

# HTTP Resilience Patterns

Resilient HTTP client patterns used by chatgpt-library-archiver for downloading images from ChatGPT's API with retry logic, streaming, and validation.

**When to use this skill:**
- Implementing or modifying HTTP download logic
- Adding retry/backoff behavior
- Validating downloaded content
- Handling HTTP errors and edge cases
- Designing download pipelines

## Client Architecture

The archiver uses a purpose-built `HttpClient` class wrapping `requests.Session` with:

- **Automatic retries** via `urllib3.util.retry.Retry` on the `HTTPAdapter`
- **Configurable timeouts** (connect + read)
- **Streaming downloads** with checksum computation
- **Structured errors** via `HttpError` with rich context
- **Thread safety** via `threading.Lock` for shared state (e.g., tracking seen URLs)

### Retry Configuration

```python
Retry(
    total=3,
    backoff_factor=1.0,       # 1s, 2s, 4s delays
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "HEAD"],
    raise_on_status=False,    # We handle status checking ourselves
)
```

Key design decisions:
- Only retry idempotent methods (GET, HEAD)
- Retry on rate limits (429) and server errors (5xx)
- Don't retry on client errors (4xx except 429)
- Use `raise_on_status=False` so we can inspect and build structured errors

## Streaming Download Pattern

```python
def download_file(self, url: str, dest: Path, headers: dict) -> DownloadResult:
    """Stream download with checksum and content-type validation."""
    response = self.session.get(url, headers=headers, stream=True)

    if response.status_code >= 400:
        raise HttpError(url=url, status_code=response.status_code,
                        reason=response.reason or "Unknown")

    hasher = hashlib.sha256()
    total_bytes = 0

    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            hasher.update(chunk)
            total_bytes += len(chunk)

    return DownloadResult(
        path=dest,
        bytes_downloaded=total_bytes,
        checksum=hasher.hexdigest(),
        content_type=response.headers.get("Content-Type"),
    )
```

### Why Streaming?

- Images can be large (10MB+) — don't load entirely into memory
- Checksum computation happens during download (no second pass)
- Progress reporting can be integrated via `tqdm` or callbacks
- Partial downloads can be detected (unexpected EOF)

## Error Handling

### Structured Errors

```python
class HttpError(RuntimeError):
    url: str
    status_code: int | None
    reason: str
    details: dict[str, object]
    response: Response | None
```

Always raise `HttpError` instead of generic exceptions — this allows callers to inspect the URL, status code, and context for logging or retry decisions.

### Error Categories

| Status | Meaning | Action |
|--------|---------|--------|
| 200 | Success | Process response |
| 301/302 | Redirect | Follow (requests does this automatically) |
| 400 | Bad request | Don't retry; likely a code bug |
| 401/403 | Auth failure | Don't retry; credentials are wrong |
| 404 | Not found | Don't retry; image may have been deleted |
| 429 | Rate limited | Retry with backoff |
| 500-504 | Server error | Retry with backoff |
| Timeout | Connection/read timeout | Retry (handled by urllib3) |

## Content Validation

After downloading, validate before keeping:

1. **Content-Type**: Verify response `Content-Type` starts with `image/`
2. **Non-empty**: Ensure `bytes_downloaded > 0`
3. **Checksum**: Store SHA-256 for deduplication and integrity verification
4. **File extension**: Ensure saved filename matches the actual content type

## Security Considerations

- **Credential headers**: Bearer tokens and cookies are sent with every request — ensure redirects don't leak them to third-party domains
- **Path sanitization**: Downloaded filenames must be sanitized before writing to disk
- **Size limits**: Consider enforcing maximum download size to prevent disk exhaustion
- **TLS verification**: Never disable SSL certificate verification (`verify=False`)

## Testing HTTP Code

- **Mock `requests.Session`** — never make real HTTP calls in tests
- **Simulate errors**: Test 4xx, 5xx, timeouts, empty responses, malformed Content-Type
- **Test retry behavior**: Verify backoff timing and max retry limits
- **Test streaming**: Verify checksum computation and partial download handling
