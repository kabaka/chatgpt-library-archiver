---
name: credential-handling
description: Secure credential management patterns for the archiver — auth token storage, API key protection, environment variable resolution, file permissions, and secrets hygiene for ChatGPT browser tokens and OpenAI API keys
---

# Credential Handling Patterns

Secure management of sensitive credentials in chatgpt-library-archiver — covering ChatGPT browser tokens, OpenAI API keys, and environment variable configuration.

**When to use this skill:**
- Handling authentication tokens or API keys
- Implementing credential storage or loading
- Reviewing code for credential leakage
- Designing configuration resolution (file vs. env var vs. CLI)
- Setting up CI/CD with secrets

## Credential Types

### 1. ChatGPT Browser Tokens (`auth.txt`)

Used to authenticate with ChatGPT's backend API for image downloads.

```
url=https://chat.openai.com/backend-api/my/recent/image_gen?limit=100
authorization=Bearer eyJhbG...
cookie=__Secure-next-auth.session-token=eyJhbG...
referer=https://chat.openai.com/library
user_agent=Mozilla/5.0 (...)
oai_client_version=...
oai_device_id=...
oai_language=...
```

**Security properties:**
- File permissions: `600` (owner read/write only)
- Listed in `.gitignore` — never committed
- Contains session tokens that can impersonate the user
- Tokens expire — users must refresh periodically

### 2. OpenAI API Key (`tagging_config.json`)

Used for vision API calls (tagging, renaming).

```json
{
  "api_key": "sk-...",
  "model": "gpt-4.1-mini",
  "prompt": "..."
}
```

**Security properties:**
- Listed in `.gitignore` — never committed
- API key has billing implications
- Can be overridden via environment variables

## Environment Variable Resolution

The archiver supports multiple env vars for API key injection:

| Variable | Priority | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Standard | Industry-standard OpenAI key |
| `CHATGPT_LIBRARY_ARCHIVER_API_KEY` | Project-specific | Avoids conflicts with other tools |
| `CHATGPT_LIBRARY_ARCHIVER_OPENAI_API_KEY` | Project-specific | Explicit naming |

Additional overrides:
- `CHATGPT_LIBRARY_ARCHIVER_OPENAI_MODEL` — Model selection
- `CHATGPT_LIBRARY_ARCHIVER_TAG_PROMPT` — Custom tagging prompt
- `CHATGPT_LIBRARY_ARCHIVER_RENAME_PROMPT` — Custom rename prompt

**Resolution order**: CLI args → env vars → config file → defaults.

## Security Rules

### Never Do

- Log credentials (even partially — no "first 4 characters")
- Include credentials in error messages or stack traces
- Write credentials to `metadata.json` or any committed file
- Embed credentials in URLs (query parameters)
- Disable TLS verification
- Store credentials in Python source code
- Send credentials in headers to redirect targets on different domains

### Always Do

- Set `600` permissions on credential files
- Load credentials at the latest possible moment
- Clear credential variables from memory when no longer needed
- Validate that `.gitignore` covers all credential files
- Use `ARCHIVER_ASSUME_YES` env var for non-interactive scripted runs (not credential-related, but avoids interactive prompts in CI)

## Interactive Credential Setup

The archiver prompts users interactively when credentials are missing:

```python
def ensure_auth_config(path: str) -> dict:
    """Load auth config, prompting user to create it if missing."""
    if os.path.exists(path):
        return load_auth_config(path)
    # Interactive: guide user through header extraction
    config = prompt_for_auth_headers()
    write_auth_config(path, config)
    os.chmod(path, 0o600)
    return config
```

For CI/scripted use, provide `--no-config-prompt` to fail fast instead of prompting.

## Testing Credential Code

- **Never use real credentials in tests**
- Use `monkeypatch.setenv()` for environment variable tests
- Use `tmp_path` for credential file tests
- Test permission setting on credential files
- Test missing/malformed credential files
- Verify credentials are not present in error output
- Test the full resolution chain: CLI → env → file → default

## Audit Checklist

- [ ] `auth.txt` in `.gitignore`
- [ ] `tagging_config.json` in `.gitignore`
- [ ] No credentials in `metadata.json`
- [ ] No credentials in log output or error messages
- [ ] File permissions set to `600`
- [ ] Env var fallbacks tested
- [ ] `--no-config-prompt` works for scripted environments
- [ ] Redirect responses don't forward auth headers to other domains
