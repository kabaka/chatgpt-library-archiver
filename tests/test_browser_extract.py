"""Tests for the browser_extract module.

All tests use mocks — never real browser data, keychain access, or credentials.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from chatgpt_library_archiver.browser_extract import (
    BrowserExtractError,
    BrowserNotFoundError,
    CookieDecryptionError,
    KeychainAccessError,
    PlatformNotSupportedError,
    SessionExpiredError,
    TokenFetchError,
    _decrypt_cookie_value,
    _derive_key,
    _get_keychain_password,
    _mask,
    _require_macos,
    _scrape_client_version,
    extract_auth_config,
    extract_cookies,
    fetch_access_token,
    fetch_oai_headers,
    write_auth_from_browser,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_PASSWORD = "fakeKeychainPassword"
_FAKE_KEY = _derive_key(_FAKE_PASSWORD)


def _encrypt_value(
    plaintext: str,
    key: bytes,
    *,
    db_version: int = 0,
    host_key: str = ".chatgpt.com",
) -> bytes:
    """Build a v10-prefixed AES-128-CBC encrypted cookie for testing.

    For *db_version* >= 24 the plaintext is prefixed with a 32-byte
    SHA-256 hash of *host_key*, matching real Chromium behaviour.
    """
    import hashlib

    data = plaintext.encode("utf-8")
    if db_version >= 24:
        domain_hash = hashlib.sha256(host_key.encode("utf-8")).digest()
        data = domain_hash + data

    # PKCS#7 padding to AES block size (16)
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len]) * pad_len

    iv = b" " * 16
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return b"v10" + ciphertext


def _make_cookie_db(
    db_path: Path,
    rows: list[tuple[str, str, bytes]],
    *,
    db_version: int = 0,
) -> None:
    """Create a minimal Chromium cookies SQLite database at *db_path*.

    *rows* is a list of ``(host_key, name, encrypted_value)`` tuples.
    When *db_version* > 0 a ``meta`` table with a ``version`` row is
    included, matching the real Chromium schema.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE cookies ("
        "  host_key TEXT NOT NULL,"
        "  name TEXT NOT NULL,"
        "  encrypted_value BLOB"
        ")"
    )
    conn.executemany(
        "INSERT INTO cookies (host_key, name, encrypted_value) VALUES (?, ?, ?)",
        rows,
    )
    if db_version > 0:
        conn.execute(
            "CREATE TABLE meta (key TEXT NOT NULL UNIQUE, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('version', ?)",
            (str(db_version),),
        )
    conn.commit()
    conn.close()


# ===================================================================
# _require_macos
# ===================================================================


def test_require_macos_on_darwin(monkeypatch):
    """No exception on macOS."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    _require_macos()  # should not raise


def test_require_macos_on_linux_raises(monkeypatch):
    """PlatformNotSupportedError on non-macOS."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(PlatformNotSupportedError, match="macOS"):
        _require_macos()


def test_require_macos_on_windows_raises(monkeypatch):
    """PlatformNotSupportedError on Windows."""
    monkeypatch.setattr("platform.system", lambda: "Windows")
    with pytest.raises(PlatformNotSupportedError, match="macOS"):
        _require_macos()


# ===================================================================
# _get_keychain_password
# ===================================================================


def test_get_keychain_password_success(monkeypatch):
    """Returns stripped stdout from the security command."""
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="  secretpass \n", stderr=""
    )
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: fake_result)
    assert _get_keychain_password("Some Service") == "secretpass"


def test_get_keychain_password_called_process_error(monkeypatch):
    """CalledProcessError → KeychainAccessError."""

    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(44, "security")

    monkeypatch.setattr("subprocess.run", _raise)
    with pytest.raises(KeychainAccessError, match="Could not retrieve"):
        _get_keychain_password("Some Service")


def test_get_keychain_password_file_not_found(monkeypatch):
    """FileNotFoundError (missing binary) → KeychainAccessError."""

    def _raise(*args, **kwargs):
        raise FileNotFoundError("security")

    monkeypatch.setattr("subprocess.run", _raise)
    with pytest.raises(KeychainAccessError, match="security"):
        _get_keychain_password("Some Service")


# ===================================================================
# _derive_key
# ===================================================================


def test_derive_key_deterministic():
    """PBKDF2 with fixed parameters is deterministic."""
    key1 = _derive_key("password123")
    key2 = _derive_key("password123")
    assert key1 == key2
    assert len(key1) == 16  # 128 bits


def test_derive_key_different_passwords():
    """Different passwords produce different keys."""
    assert _derive_key("alpha") != _derive_key("bravo")


# ===================================================================
# _decrypt_cookie_value
# ===================================================================


def test_decrypt_cookie_value_roundtrip():
    """Encrypt then decrypt produces original plaintext (legacy DB)."""
    plaintext = "session-token-value-abc123"
    encrypted = _encrypt_value(plaintext, _FAKE_KEY)
    assert _decrypt_cookie_value(encrypted, _FAKE_KEY) == plaintext


def test_decrypt_cookie_value_roundtrip_v24():
    """Encrypt then decrypt with DB version 24 domain-hash prefix."""
    plaintext = "session-token-value-abc123"
    encrypted = _encrypt_value(
        plaintext,
        _FAKE_KEY,
        db_version=24,
        host_key=".chatgpt.com",
    )
    assert _decrypt_cookie_value(encrypted, _FAKE_KEY, db_version=24) == plaintext


def test_decrypt_cookie_value_unencrypted():
    """Non v10-prefixed UTF-8 bytes are returned as-is."""
    raw = b"plain-cookie-value"
    assert _decrypt_cookie_value(raw, _FAKE_KEY) == "plain-cookie-value"


def test_decrypt_cookie_value_invalid_length_raises():
    """Payload not a multiple of 16 → CookieDecryptionError."""
    encrypted = b"v10" + b"\x00" * 5
    with pytest.raises(CookieDecryptionError, match="invalid length"):
        _decrypt_cookie_value(encrypted, _FAKE_KEY)


def test_decrypt_cookie_value_wrong_key_raises():
    """Wrong key → CookieDecryptionError (invalid PKCS#7 padding)."""
    encrypted = _encrypt_value("hello", _FAKE_KEY)
    wrong_key = _derive_key("wrong-password")
    with pytest.raises(CookieDecryptionError, match=r"padding|UTF-8"):
        _decrypt_cookie_value(encrypted, wrong_key)


def test_decrypt_cookie_value_non_utf8_unencrypted_raises():
    """Non-UTF-8 bytes without v10 prefix → CookieDecryptionError."""
    raw = b"\x80\xff\xfe"
    with pytest.raises(CookieDecryptionError, match="unrecognised"):
        _decrypt_cookie_value(raw, _FAKE_KEY)


# ===================================================================
# extract_cookies
# ===================================================================


def test_extract_cookies_happy_path(tmp_path, monkeypatch):
    """Reads and decrypts cookies from a temporary SQLite database."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    # Create a fake cookie database
    db_path = tmp_path / "Cookies"
    session_value = "session-tok-xyz"
    did_value = "did-abc-123"
    encrypted_session = _encrypt_value(session_value, _FAKE_KEY)
    encrypted_did = _encrypt_value(did_value, _FAKE_KEY)
    _make_cookie_db(
        db_path,
        [
            (".chatgpt.com", "__Secure-next-auth.session-token", encrypted_session),
            (".chatgpt.com", "oai-did", encrypted_did),
        ],
    )

    # Patch the profile to point at our temp database
    fake_profile = MagicMock()
    fake_profile.name = "Test Browser"
    fake_profile.cookies_path = db_path
    fake_profile.keychain_service = "Test Safe Storage"
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._PROFILES",
        {"test": fake_profile},
    )
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._get_keychain_password",
        lambda _service: _FAKE_PASSWORD,
    )

    cookies = extract_cookies("test")
    assert cookies["__Secure-next-auth.session-token"] == session_value
    assert cookies["oai-did"] == did_value


def test_extract_cookies_missing_db_raises(tmp_path, monkeypatch):
    """BrowserNotFoundError when the cookie file does not exist."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    fake_profile = MagicMock()
    fake_profile.name = "Test Browser"
    fake_profile.cookies_path = tmp_path / "does_not_exist"
    fake_profile.keychain_service = "Test Safe Storage"
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._PROFILES",
        {"test": fake_profile},
    )

    with pytest.raises(BrowserNotFoundError, match="not found"):
        extract_cookies("test")


def test_extract_cookies_unsupported_browser_raises(monkeypatch):
    """BrowserExtractError for an unknown browser key."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    with pytest.raises(BrowserExtractError, match="Unsupported browser"):
        extract_cookies("firefox")


def test_extract_cookies_non_darwin_raises(monkeypatch):
    """PlatformNotSupportedError on non-macOS."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(PlatformNotSupportedError):
        extract_cookies("edge")


def test_extract_cookies_skips_undecryptable(tmp_path, monkeypatch):
    """Cookies that fail decryption are silently skipped."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    db_path = tmp_path / "Cookies"
    good_encrypted = _encrypt_value("good-value", _FAKE_KEY)
    # Corrupt: v10 prefix + payload that isn't a multiple of 16 → decryption fails
    bad_encrypted = b"v10" + os.urandom(17)

    _make_cookie_db(
        db_path,
        [
            (".chatgpt.com", "good_cookie", good_encrypted),
            (".chatgpt.com", "bad_cookie", bad_encrypted),
        ],
    )

    fake_profile = MagicMock()
    fake_profile.name = "Test Browser"
    fake_profile.cookies_path = db_path
    fake_profile.keychain_service = "Test Safe Storage"
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._PROFILES",
        {"test": fake_profile},
    )
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._get_keychain_password",
        lambda _service: _FAKE_PASSWORD,
    )

    cookies = extract_cookies("test")
    assert "good_cookie" in cookies
    assert "bad_cookie" not in cookies


def test_extract_cookies_temp_copy_permissions(tmp_path, monkeypatch):
    """Cookie DB copy is chmod 0o600 and temp dir is cleaned up."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    db_path = tmp_path / "Cookies"
    encrypted = _encrypt_value("value", _FAKE_KEY)
    _make_cookie_db(db_path, [(".chatgpt.com", "c", encrypted)])

    fake_profile = MagicMock()
    fake_profile.name = "Test Browser"
    fake_profile.cookies_path = db_path
    fake_profile.keychain_service = "Test Safe Storage"
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._PROFILES",
        {"test": fake_profile},
    )
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._get_keychain_password",
        lambda _service: _FAKE_PASSWORD,
    )

    # Track chmod calls to verify 0o600 is set on copied DB
    chmod_calls: list[tuple[object, int]] = []
    original_chmod = os.chmod

    def _track_chmod(path, mode, *args, **kwargs):
        chmod_calls.append((path, mode))
        return original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.os.chmod",
        _track_chmod,
    )

    extract_cookies("test")

    # At least one chmod call should set 0o600 on a file named "Cookies"
    assert any(
        str(p).endswith("Cookies") and m == 0o600 for p, m in chmod_calls
    ), f"Expected chmod 0o600 on Cookies copy, got: {chmod_calls}"


# ===================================================================
# _mask
# ===================================================================


def test_mask_short_string():
    """Strings ≤ visible length → '***'."""
    assert _mask("short") == "***"
    assert _mask("12345678") == "***"


def test_mask_long_string():
    """Strings > visible length → first 8 chars + '...'."""
    assert _mask("abcdefghijklmnop") == "abcdefgh..."


def test_mask_custom_visible():
    """Custom visible parameter."""
    assert _mask("abcdefghij", visible=4) == "abcd..."


# ===================================================================
# fetch_access_token
# ===================================================================


def test_fetch_access_token_success(monkeypatch):
    """Returns the accessToken from a successful session response."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(json_data={"accessToken": "tok_123"}),
    )
    assert fetch_access_token("fake-session-cookie") == "tok_123"


def test_fetch_access_token_disables_redirects(monkeypatch):
    """fetch_access_token passes allow_redirects=False to the session."""
    captured_kwargs: list[dict] = []

    class _CapturingResponse:
        status_code = 200

        def json(self):
            return {"accessToken": "tok"}

    class _CapturingSession:
        def get(self, url, **kwargs):
            captured_kwargs.append(kwargs)
            return _CapturingResponse()

    class _CapturingClient:
        def __init__(self, **_kw):
            self.timeout = 30.0

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

        def _get_session(self):
            return _CapturingSession()

    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _CapturingClient,
    )
    fetch_access_token("cookie")
    assert captured_kwargs[0].get("allow_redirects") is False


def test_fetch_access_token_401_raises(monkeypatch):
    """HTTP 401 → SessionExpiredError."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(status_code=401),
    )
    with pytest.raises(SessionExpiredError, match="expired"):
        fetch_access_token("expired-cookie")


def test_fetch_access_token_403_raises(monkeypatch):
    """HTTP 403 → SessionExpiredError."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(status_code=403),
    )
    with pytest.raises(SessionExpiredError, match="expired"):
        fetch_access_token("expired-cookie")


def test_fetch_access_token_missing_key_raises(monkeypatch):
    """Response without accessToken → SessionExpiredError."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(json_data={"user": "bob"}),
    )
    with pytest.raises(SessionExpiredError, match="did not return"):
        fetch_access_token("fake-session-cookie")


def test_fetch_access_token_empty_token_raises(monkeypatch):
    """Empty accessToken string → SessionExpiredError."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(json_data={"accessToken": ""}),
    )
    with pytest.raises(SessionExpiredError, match="did not return"):
        fetch_access_token("fake-session-cookie")


def test_fetch_access_token_server_error_raises(monkeypatch):
    """HTTP 500 → TokenFetchError (not SessionExpiredError)."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(status_code=500),
    )
    with pytest.raises(TokenFetchError, match="Failed to fetch"):
        fetch_access_token("some-cookie")


def test_fetch_access_token_invalid_json_raises(monkeypatch):
    """Non-JSON response body → TokenFetchError."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client(invalid_json=True),
    )
    with pytest.raises(TokenFetchError, match="invalid JSON"):
        fetch_access_token("some-cookie")


# ===================================================================
# fetch_oai_headers
# ===================================================================


def test_fetch_oai_headers_with_device_id(monkeypatch):
    """Uses provided device_id and default language."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._scrape_client_version",
        lambda _cookie: "build-42",
    )
    result = fetch_oai_headers("fake-cookie", device_id="my-device-id")
    assert result["oai_device_id"] == "my-device-id"
    assert result["oai_client_version"] == "build-42"
    assert result["oai_language"] == "en-US"


def test_fetch_oai_headers_generates_uuid_when_no_device_id(monkeypatch):
    """Generates a UUID when device_id is None."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._scrape_client_version",
        lambda _cookie: "",
    )
    result = fetch_oai_headers("fake-cookie", device_id=None)
    # Should be a valid UUID4-like string (contains hyphens, 36 chars)
    assert len(result["oai_device_id"]) == 36
    assert "-" in result["oai_device_id"]


def test_fetch_oai_headers_default_language(monkeypatch):
    """oai_language defaults to en-US."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract._scrape_client_version",
        lambda _cookie: "",
    )
    result = fetch_oai_headers("fake-cookie")
    assert result["oai_language"] == "en-US"


# ===================================================================
# _scrape_client_version
# ===================================================================


def test_scrape_client_version_extracts_build_id(monkeypatch):
    """Finds buildId in HTML response."""
    html = '<script>{"buildId":"abc123XYZ","other":"stuff"}</script>'
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client_for_scrape(html),
    )
    assert _scrape_client_version("fake-cookie") == "abc123XYZ"


def test_scrape_client_version_http_failure_returns_empty(monkeypatch):
    """HTTP error → empty string (best-effort)."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client_for_scrape(exc=RuntimeError("network down")),
    )
    assert _scrape_client_version("fake-cookie") == ""


def test_scrape_client_version_no_match_returns_empty(monkeypatch):
    """HTML without buildId → empty string."""
    html = "<html><body>Nothing here</body></html>"
    monkeypatch.setattr(
        "chatgpt_library_archiver.http_client.HttpClient",
        _make_mock_http_client_for_scrape(html),
    )
    assert _scrape_client_version("fake-cookie") == ""


# ===================================================================
# extract_auth_config
# ===================================================================


def test_extract_auth_config_happy_path(monkeypatch):
    """Full pipeline returns dict with all required keys."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_cookies",
        lambda browser: {
            "__Secure-next-auth.session-token": "sess-tok",
            "oai-did": "device-123",
        },
    )
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.fetch_access_token",
        lambda cookie: "access-tok-456",
    )
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.fetch_oai_headers",
        lambda cookie, device_id=None: {
            "oai_client_version": "v1",
            "oai_device_id": device_id or "gen-uuid",
            "oai_language": "en-US",
        },
    )

    config = extract_auth_config("edge")
    assert config["authorization"] == "Bearer access-tok-456"
    assert "__Secure-next-auth.session-token=sess-tok" in config["cookie"]
    assert config["oai_device_id"] == "device-123"
    assert config["oai_language"] == "en-US"
    assert config["url"].startswith("https://")
    assert config["referer"].startswith("https://")
    assert "user_agent" in config


def test_extract_auth_config_missing_session_cookie_raises(monkeypatch):
    """Missing session cookie → SessionExpiredError."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_cookies",
        lambda browser: {"oai-did": "device-123"},
    )
    with pytest.raises(SessionExpiredError, match="session-token"):
        extract_auth_config("edge")


# ===================================================================
# write_auth_from_browser
# ===================================================================


def test_write_auth_from_browser_writes_file(tmp_path, monkeypatch):
    """Writes auth config to disk with correct content."""
    fake_config = {
        "url": "https://chatgpt.com/backend-api/my/recent/image_gen?limit=100",
        "authorization": "Bearer tok",
        "cookie": "__Secure-next-auth.session-token=sess",
        "referer": "https://chatgpt.com/library",
        "user_agent": "MockAgent/1.0",
        "oai_client_version": "v1",
        "oai_device_id": "dev-1",
        "oai_language": "en-US",
    }
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        lambda browser: fake_config,
    )

    auth_path = str(tmp_path / "auth.txt")
    result = write_auth_from_browser("edge", auth_path)

    assert result == fake_config

    content = Path(auth_path).read_text(encoding="utf-8")
    for key, value in fake_config.items():
        assert f"{key}={value}" in content


def test_write_auth_from_browser_permissions(tmp_path, monkeypatch):
    """Output file has 0o600 permissions."""
    monkeypatch.setattr(
        "chatgpt_library_archiver.browser_extract.extract_auth_config",
        lambda browser: {"key": "value"},
    )

    auth_path = str(tmp_path / "auth.txt")
    write_auth_from_browser("edge", auth_path)

    mode = stat.S_IMODE(os.stat(auth_path).st_mode)
    assert mode == 0o600


# ===================================================================
# Mock helpers for HttpClient
# ===================================================================


def _make_mock_http_client(
    *,
    json_data: dict | None = None,
    status_code: int = 200,
    invalid_json: bool = False,
):
    """Return a class that mimics HttpClient as a context manager.

    ``fetch_access_token`` now uses ``client._get_session()`` directly,
    so the mock exposes a fake session whose ``get()`` returns a
    ``_FakeResponse`` with the given *status_code* and *json_data*.
    """

    class _FakeResponse:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            if invalid_json:
                raise ValueError("No JSON")
            return json_data or {}

    class _FakeSession:
        def get(self, url, *, headers=None, timeout=None, allow_redirects=None):
            return _FakeResponse()

    class _MockHttpClient:
        def __init__(self, **_kwargs):
            self.timeout = _kwargs.get("timeout", 30.0)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def _get_session(self):
            return _FakeSession()

    return _MockHttpClient


def _make_mock_http_client_for_scrape(
    html: str | None = None,
    exc: Exception | None = None,
):
    """Return a class that mimics HttpClient for _scrape_client_version.

    The scrape function accesses ``client._get_session().get(...).text``.
    """

    class _FakeResponse:
        def __init__(self):
            self.text = html or ""

    class _FakeSession:
        def get(self, url, *, headers=None, timeout=None, allow_redirects=None):
            if exc:
                raise exc
            return _FakeResponse()

    class _MockHttpClient:
        def __init__(self, **_kwargs):
            self.timeout = _kwargs.get("timeout", 30.0)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def _get_session(self):
            return _FakeSession()

    return _MockHttpClient
