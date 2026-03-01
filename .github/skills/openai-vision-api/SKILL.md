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

The archiver caches `OpenAI` client instances per API key to avoid creating new connections for every request:

```python
_CLIENT_CACHE: dict[str, OpenAI] = {}

def get_cached_client(api_key: str) -> OpenAI:
    client = _CLIENT_CACHE.get(api_key)
    if client is None:
        client = OpenAI(api_key=api_key)
        _CLIENT_CACHE[api_key] = client
    return client
```

Always use `get_cached_client()` — never construct `OpenAI()` directly in feature code.

## Vision API Call Pattern

### Image Encoding

```python
import base64
import mimetypes

def encode_image_for_api(image_path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type) for an image file."""
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, mime_type
```

### API Call Structure

```python
response = client.chat.completions.create(
    model=model,
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {
                "url": f"data:{media_type};base64,{base64_data}"
            }}
        ]
    }],
    max_tokens=300,
)
result = response.choices[0].message.content
```

## Rate Limit Handling

```python
from openai import RateLimitError

MAX_RETRIES = 3
BASE_DELAY = 2.0

for attempt in range(MAX_RETRIES):
    try:
        response = client.chat.completions.create(...)
        break
    except RateLimitError:
        if attempt == MAX_RETRIES - 1:
            raise
        delay = BASE_DELAY * (2 ** attempt)
        time.sleep(delay)
```

Key considerations:
- Always use exponential backoff, not fixed delays
- Track retry count in telemetry (`AIRequestTelemetry.retries`)
- Respect `Retry-After` headers when present
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

1. **CLI arguments** (highest priority)
2. **Environment variables**: `OPENAI_API_KEY`, `CHATGPT_LIBRARY_ARCHIVER_API_KEY`, `CHATGPT_LIBRARY_ARCHIVER_OPENAI_API_KEY`
3. **Config file**: `tagging_config.json` (`api_key`, `model`, `prompt`)
4. **Defaults**: model = `gpt-4.1-mini`, prompt = built-in default

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
