---
name: openai-vision-api
description: OpenAI vision API integration patterns for image tagging and renaming — prompt engineering, base64 encoding, rate limit handling, client caching, telemetry, and configuration management
---

# OpenAI Vision API Patterns

Integration patterns for using the OpenAI vision API to tag and rename images in chatgpt-library-archiver.

**When to use this skill:**
- Implementing or modifying AI tagging features
- Writing prompts for image analysis
- Handling rate limits and API errors
- Managing OpenAI client lifecycle and caching
- Configuring API keys and model selection

## Client Lifecycle

### Cached Client Pattern

The archiver caches `OpenAI` client instances per API key to avoid creating new connections for every request. The SDK's own retry is disabled (`max_retries=0`) so that the application-level retry loop in `call_image_endpoint` has full control:

```python
_CLIENT_CACHE: dict[str, OpenAI] = {}

def get_cached_client(api_key: str) -> OpenAI:
    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = OpenAI(api_key=api_key, max_retries=0)
        _CLIENT_CACHE[api_key] = client
    return client
```

Always use `get_cached_client()` — never construct `OpenAI()` directly in feature code. Use `reset_client_cache()` in tests to clear cached clients between test runs.

## Vision API Call Pattern

### Image Encoding

The `encode_image()` function in `ai.py` returns `(mime, data_url)` for use in API calls. It applies smart preprocessing for large files:

- Files **≤ 500 KB**: passed through as-is (raw base64)
- Files **> 500 KB**: resized so the longest dimension ≤ 1024 px, EXIF-transposed, and converted to JPEG (saves 60–80% on token costs)
- **RGBA** images: composited onto a white background before JPEG conversion
- **BMP/TIFF**: converted to JPEG when resized

```python
def encode_image(image_path: Path, *, max_dimension: int = 1024) -> tuple[str, str]:
    """Return (mime, data_url) for image_path suitable for API calls."""
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    file_size = image_path.stat().st_size

    if file_size > _ENCODE_SIZE_THRESHOLD:  # 500_000 bytes
        # Open with Pillow, EXIF transpose, resize, convert to JPEG
        ...
        return "image/jpeg", f"data:image/jpeg;base64,{payload}"

    # Small file — pass through as-is
    with image_path.open("rb") as fh:
        payload = base64.b64encode(fh.read()).decode("ascii")
    return mime, f"data:{mime};base64,{payload}"
```

### API Call Structure

The archiver uses the OpenAI **Responses API** (`client.responses.create`), not the Chat Completions API:

```python
input_messages = [
    {
        "role": "user",
        "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": data_url},
        ],
    }
]

response = client.responses.create(
    model=model,
    input=input_messages,
    max_output_tokens=300,  # 300 for tagging, 50 for renaming
)

# Safe extraction — output_text may be None (e.g. content-filtered)
output_text = getattr(response, "output_text", None)
text = "" if output_text is None else output_text.strip()
```

Key differences from the Chat Completions API:
- Method: `responses.create` (not `chat.completions.create`)
- Parameter: `input=` (not `messages=`)
- Content types: `input_text` / `input_image` (not `text` / `image_url`)
- Token cap: `max_output_tokens=` (not `max_tokens=`)
- Result: `response.output_text` (not `response.choices[0].message.content`)

## Retry & Error Handling

The `call_image_endpoint()` function retries transient errors with exponential backoff, while fatal errors propagate immediately:

```python
from openai import (
    APIConnectionError, APITimeoutError, AuthenticationError,
    BadRequestError, InternalServerError, RateLimitError,
)

def _is_transient(exc: Exception) -> bool:
    return isinstance(exc, (
        RateLimitError, APIConnectionError, APITimeoutError, InternalServerError,
    ))

# Inside call_image_endpoint:
while True:
    try:
        response = client.responses.create(...)
        break
    except (AuthenticationError, BadRequestError):
        raise  # Fatal — never retry
    except Exception as exc:
        if not _is_transient(exc) or retries >= max_retries:
            raise
        if on_retry:
            on_retry(retries + 1, delay)
        time.sleep(delay)
        retries += 1
        delay *= 2  # Exponential backoff
```

Key considerations:
- **Transient** (retried): `RateLimitError`, `APIConnectionError`, `APITimeoutError`, `InternalServerError`
- **Fatal** (never retried): `AuthenticationError`, `BadRequestError`
- Always use exponential backoff, not fixed delays
- Track retry count in telemetry (`AIRequestTelemetry.retries`)
- The SDK's own retry is disabled (`max_retries=0`) to avoid double-retry
- Cap concurrent workers to avoid hitting rate limits in the first place

## Telemetry

Every API call should capture telemetry:

```python
@dataclass(slots=True)
class AIRequestTelemetry:
    operation: str          # "tag" or "rename"
    subject: str | None     # image filename
    latency_s: float        # wall-clock time
    total_tokens: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    retries: int
```

Report telemetry via callback to `StatusReporter` for consistent logging.

## Configuration Resolution

The archiver resolves OpenAI configuration from multiple sources in priority order:

1. **CLI arguments** (highest priority — except API key, which cannot be overridden via CLI)
2. **Environment variables**: `CHATGPT_LIBRARY_ARCHIVER_OPENAI_API_KEY`, `CHATGPT_LIBRARY_ARCHIVER_API_KEY`, `OPENAI_API_KEY` (checked in that order)
3. **Config file**: `tagging_config.json` (`api_key`, `model`, `prompt`, `rename_prompt`)
4. **Defaults**: model = `gpt-4.1-mini` (`DEFAULT_MODEL` in `ai.py`), prompt = built-in default in `tagger.py`

Configuration is resolved into a `TaggingConfig` dataclass:

```python
@dataclass(slots=True)
class TaggingConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    prompt: str = ""
    rename_prompt: str | None = None
```

This layered resolution supports both interactive use and CI/scripted environments.

## Prompt Engineering

### Tagging Prompt

The default tagging prompt produces comma-separated descriptive tags:

```
Generate concise, comma-separated descriptive tags for this image
in the style of booru archives.
```

**Design principles:**
- Request structured output (comma-separated) for easy parsing
- Reference a known style (booru) for consistent tag vocabulary
- Keep concise to minimize prompt tokens
- Allow user override via config

### Rename Prompt

```
Create a short, descriptive filename slug (kebab-case, <=6 words) for this image.
```

**Design principles:**
- Constrain output format (kebab-case)
- Constrain length (≤6 words)
- Request descriptive content for searchability

### Prompt Testing

When modifying prompts:
1. Test against diverse image types (photos, illustrations, screenshots, abstract)
2. Verify output format is parseable
3. Check token usage doesn't exceed budget
4. Ensure results are deterministic enough for production use

## Two Separate APIs

This project uses two unrelated APIs:

| API | Purpose | Auth | SDK |
|-----|---------|------|-----|
| ChatGPT Backend | Download images from user library | Browser tokens (Bearer + cookie) | `requests` |
| OpenAI API | Vision tagging / renaming | API key | `openai` SDK |

Never mix these authentication mechanisms. They serve completely different purposes.
