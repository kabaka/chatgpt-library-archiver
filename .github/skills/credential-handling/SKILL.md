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
url=https://chatgpt.com/backend-api/my/recent/image_gen?limit=100
authorization=Bearer eyJhbG...
cookie=__Secure-next-auth.session-token=eyJhbG...
referer=https://chatgpt.com/library
user_agent=Mozilla/5.0 (...)
oai_client_version=...
oai_device_id=...
oai_language=...
```

**Security properties:**
- File permissions: `600` (owner read/write only), enforced by `write_secure_file()`
- Listed in `.gitignore` — never committed
- Contains session tokens that can impersonate the user
- Tokens expire — users must refresh periodically

**Acquisition methods** (in order of preference):

1. **`extract-auth` CLI command** (recommended for macOS) — automatically extracts credentials from Edge or Chrome browser cookies, fetches the Bearer token, and writes `auth.txt`:
   ```bash
   chatgpt-archiver extract-auth --browser edge
   chatgpt-archiver extract-auth --browser chrome --output auth.txt
   chatgpt-archiver extract-auth --dry-run  # preview without writing
   ```
2. **Manual extraction** — copy headers from browser DevTools → Network tab

See the [Browser Credential Extraction](#browser-credential-extraction-extract-auth) section below for details.

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
def ensure_auth_config(path: str = "auth.txt") -> AuthConfig:
    """Load auth config, prompting user to create it if missing."""
    try:
        cfg = load_auth_config(path)
    except FileNotFoundError:
        if prompt_yes_no("auth.txt not found. Create it now?"):
            cfg = prompt_and_write_auth(path)
        else:
            raise
    # Validate required keys are present
    missing = [k for k in REQUIRED_AUTH_KEYS if not cfg.get(k)]
    if missing:
        if prompt_yes_no("auth.txt is missing required keys. Re-enter credentials now?"):
            cfg = prompt_and_write_auth(path)
        else:
            raise ValueError("auth.txt is missing required keys")
    return cfg
```

Sensitive fields (`authorization`, `cookie`) are collected via `getpass.getpass()` to avoid terminal echo. A masked confirmation is displayed after entry (e.g. `✓ authorization set: Bearer e...`).

For CI/scripted use, set `ARCHIVER_ASSUME_YES=1` to auto-answer prompts. For tagging config, pass `allow_interactive=False` to `ensure_tagging_config()` to fail fast instead of prompting.

## Browser Credential Extraction (`extract-auth`)

The `extract-auth` CLI command automates credential acquisition on macOS by reading encrypted cookies from Chromium-based browsers (Edge, Chrome).

### How It Works

1. **Cookie extraction** — copies the browser's SQLite cookie database to a temp location, reads `chatgpt.com` cookies
2. **Decryption** — retrieves the encryption key from the macOS Keychain via `security find-generic-password`, derives AES-128-CBC key via PBKDF2, decrypts cookie values
3. **Token exchange** — uses the session cookie to call ChatGPT's `/api/auth/session` endpoint for a Bearer access token
4. **Header discovery** — fetches the ChatGPT page to extract `oai_client_version` (build ID), generates a device UUID
5. **File writing** — writes `auth.txt` with `0o600` permissions via `write_secure_file()`

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--browser` | `edge` | Browser to extract from (`edge` or `chrome`) |
| `--output` | `auth.txt` | Path to write the auth file |
| `--dry-run` | — | Print extracted values (sensitive fields masked) without writing |
| `--no-verify` | — | Skip the test API call that confirms the token works |

### Security Considerations

- The macOS Keychain dialog may appear asking the user to grant access — this is expected
- Cookie database is copied to a temp directory to avoid SQLite locking
- Decrypted cookies and tokens are only held in memory during extraction
- `--dry-run` masks sensitive fields (authorization, cookie) via `_mask()` helper
- The verification step makes a lightweight API call to confirm the token is valid

### Platform Limitations

- **macOS only** — raises `PlatformNotSupportedError` on non-Darwin systems
- Requires the browser's "Default" profile to have been used
- Cookie database version 24+ (Edge 145+, Chrome 131+) prepends a 32-byte SHA-256 domain hash to encrypted values — handled automatically

### Error Types

All extraction errors inherit from `BrowserExtractError`:
- `PlatformNotSupportedError` — not macOS
- `BrowserNotFoundError` — cookie database missing
- `KeychainAccessError` — Keychain password retrieval failed
- `CookieDecryptionError` — AES decryption failed
- `SessionExpiredError` — session cookie missing or expired
- `TokenFetchError` — access token API call failed

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
- [ ] File permissions set to `600` via `write_secure_file()`
- [ ] Env var fallbacks tested
- [ ] `ARCHIVER_ASSUME_YES` works for scripted environments
- [ ] `allow_interactive=False` works for tagging config in CI
- [ ] `extract-auth --dry-run` masks sensitive fields
- [ ] Redirect responses don't forward auth headers to other domains
