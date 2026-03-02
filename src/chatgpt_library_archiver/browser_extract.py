"""Extract authentication credentials from Chromium-based browsers on macOS.

Reads encrypted cookies from Edge/Chrome SQLite databases, decrypts them
using the macOS Keychain, and fetches the Bearer token and OAI headers
needed for ``auth.txt``.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from hashlib import pbkdf2_hmac
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHATGPT_HOST = "%chatgpt.com%"
_SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
_OAI_DID_COOKIE_NAME = "oai-did"

_SESSION_URL = "https://chatgpt.com/api/auth/session"
_CHATGPT_PAGE_URL = "https://chatgpt.com/"

_AUTH_URL_DEFAULT = "https://chatgpt.com/backend-api/my/recent/image_gen?limit=100"
_REFERER_DEFAULT = "https://chatgpt.com/library"
_OAI_LANGUAGE_DEFAULT = "en-US"

# Chromium PBKDF2 parameters on macOS
_PBKDF2_SALT = b"saltysalt"
_PBKDF2_ITERATIONS = 1003
_PBKDF2_KEY_LENGTH = 16

# Encrypted value prefix for Chromium on macOS (AES-128-CBC)
_V10_PREFIX = b"v10"
_CBC_IV = b" " * 16

# Cookie database version 24+ prepends a 32-byte SHA-256 domain hash
# to the plaintext before encryption.
_DOMAIN_HASH_LENGTH = 32
_MIN_COOKIE_DB_VERSION_WITH_HASH = 24

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)


@dataclass(slots=True)
class BrowserProfile:
    """Location and keychain metadata for a Chromium-based browser."""

    name: str
    cookies_path: Path
    keychain_service: str


_PROFILES: dict[str, BrowserProfile] = {
    "edge": BrowserProfile(
        name="Microsoft Edge",
        cookies_path=Path.home()
        / "Library"
        / "Application Support"
        / "Microsoft Edge"
        / "Default"
        / "Cookies",
        keychain_service="Microsoft Edge Safe Storage",
    ),
    "chrome": BrowserProfile(
        name="Google Chrome",
        cookies_path=Path.home()
        / "Library"
        / "Application Support"
        / "Google"
        / "Chrome"
        / "Default"
        / "Cookies",
        keychain_service="Chrome Safe Storage",
    ),
}


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class BrowserExtractError(RuntimeError):
    """Base error for browser credential extraction failures."""


class PlatformNotSupportedError(NotImplementedError):
    """Raised when the current platform is not macOS."""


class BrowserNotFoundError(BrowserExtractError):
    """Raised when the browser cookie database cannot be located."""


class KeychainAccessError(BrowserExtractError):
    """Raised when the macOS Keychain password cannot be retrieved."""


class CookieDecryptionError(BrowserExtractError):
    """Raised when a cookie value cannot be decrypted."""


class SessionExpiredError(BrowserExtractError):
    """Raised when the ChatGPT session cookie is missing or expired."""


class TokenFetchError(BrowserExtractError):
    """Raised when the access token cannot be obtained from ChatGPT."""


# ---------------------------------------------------------------------------
# Masking helper (security: never log full secrets)
# ---------------------------------------------------------------------------


def _mask(value: str, visible: int = 8) -> str:
    """Return a masked representation of *value* for display."""
    if len(value) <= visible:
        return "***"
    return value[:visible] + "..."


# ---------------------------------------------------------------------------
# Platform guard
# ---------------------------------------------------------------------------


def _require_macos() -> None:
    if platform.system() != "Darwin":
        msg = (
            "Browser cookie extraction is only supported on macOS. "
            f"Current platform: {platform.system()}"
        )
        raise PlatformNotSupportedError(msg)


# ---------------------------------------------------------------------------
# Keychain access
# ---------------------------------------------------------------------------


def _get_keychain_password(service: str) -> str:
    """Retrieve the encryption password from macOS Keychain.

    The ``security`` command may trigger a system dialog asking the user
    to grant access — this is expected behaviour.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                service,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        msg = "The 'security' command-line tool was not found."
        raise KeychainAccessError(msg) from exc
    except subprocess.CalledProcessError as exc:
        msg = (
            f"Could not retrieve the encryption password for '{service}' "
            "from the macOS Keychain. You may need to allow access in "
            "the macOS security dialog that appeared."
        )
        raise KeychainAccessError(msg) from exc

    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Key derivation & decryption
# ---------------------------------------------------------------------------


def _derive_key(password: str) -> bytes:
    """Derive the AES-128-CBC key from the Keychain password."""
    return pbkdf2_hmac(
        "sha1",
        password.encode("utf-8"),
        _PBKDF2_SALT,
        _PBKDF2_ITERATIONS,
        dklen=_PBKDF2_KEY_LENGTH,
    )


def _decrypt_cookie_value(
    encrypted: bytes,
    key: bytes,
    db_version: int = 0,
) -> str:
    """Decrypt a Chromium (macOS) AES-128-CBC encrypted cookie.

    On macOS, Chromium-based browsers encrypt cookies with AES-128-CBC
    using an IV of 16 space bytes (``0x20``).  Starting with cookie
    database version 24, a 32-byte SHA-256 hash of the cookie's domain
    is prepended to the plaintext before encryption.
    """
    if not encrypted.startswith(_V10_PREFIX):
        # Unencrypted or unknown format — try returning as-is
        try:
            return encrypted.decode("utf-8")
        except UnicodeDecodeError:
            msg = "Cookie value has an unrecognised encryption prefix."
            raise CookieDecryptionError(msg)  # noqa: B904

    payload = encrypted[len(_V10_PREFIX) :]
    if len(payload) == 0 or len(payload) % 16 != 0:
        msg = "Encrypted cookie value has an invalid length for AES-CBC."
        raise CookieDecryptionError(msg)

    cipher = Cipher(algorithms.AES(key), modes.CBC(_CBC_IV))
    decryptor = cipher.decryptor()
    try:
        decrypted = decryptor.update(payload) + decryptor.finalize()
    except Exception as exc:
        msg = "Failed to decrypt cookie value — the encryption key may be wrong."
        raise CookieDecryptionError(msg) from exc

    # Strip the SHA-256 domain hash added in cookie DB version 24+.
    if db_version >= _MIN_COOKIE_DB_VERSION_WITH_HASH:
        decrypted = decrypted[_DOMAIN_HASH_LENGTH:]

    # PKCS #7 unpadding
    pad_len = decrypted[-1]
    if not (1 <= pad_len <= 16) or decrypted[-pad_len:] != bytes([pad_len]) * pad_len:  # noqa: PLR2004
        msg = "Invalid PKCS#7 padding after decryption."
        raise CookieDecryptionError(msg)
    plaintext = decrypted[:-pad_len]

    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "Decrypted cookie value is not valid UTF-8."
        raise CookieDecryptionError(msg) from exc


# ---------------------------------------------------------------------------
# Cookie extraction
# ---------------------------------------------------------------------------


def _read_cookie_db_version(conn: sqlite3.Connection) -> int:
    """Read the cookie database schema version from the ``meta`` table.

    Returns ``0`` when the meta table or version key is missing.
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'version'",
        ).fetchone()
        if row:
            return int(row[0])
    except (sqlite3.OperationalError, ValueError):
        pass
    return 0


def extract_cookies(browser: str = "edge") -> dict[str, str]:
    """Read and decrypt chatgpt.com cookies from *browser*.

    Returns a dict mapping cookie name to its decrypted value.
    """
    _require_macos()

    profile = _PROFILES.get(browser)
    if profile is None:
        supported = ", ".join(sorted(_PROFILES))
        msg = f"Unsupported browser '{browser}'. Supported: {supported}"
        raise BrowserExtractError(msg)

    if not profile.cookies_path.exists():
        msg = (
            f"{profile.name} cookie database not found at "
            f"{profile.cookies_path}. Is {profile.name} installed and "
            "has the 'Default' profile been used?"
        )
        raise BrowserNotFoundError(msg)

    password = _get_keychain_password(profile.keychain_service)
    key = _derive_key(password)

    # Copy the database to a temp location to avoid SQLite locking
    with tempfile.TemporaryDirectory(prefix="archiver_cookies_") as tmp_dir:
        tmp_db = Path(tmp_dir) / "Cookies"
        shutil.copy2(profile.cookies_path, tmp_db)
        os.chmod(tmp_db, 0o600)

        conn = sqlite3.connect(str(tmp_db))
        try:
            db_version = _read_cookie_db_version(conn)
            cursor = conn.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                (_CHATGPT_HOST,),
            )
            cookies: dict[str, str] = {}
            for name, encrypted_value in cursor.fetchall():
                if not encrypted_value:
                    continue
                try:
                    cookies[name] = _decrypt_cookie_value(
                        encrypted_value,
                        key,
                        db_version=db_version,
                    )
                except CookieDecryptionError:
                    # Skip cookies that fail to decrypt — only the session
                    # cookie is strictly required. Callers will check later.
                    continue
        finally:
            conn.close()

    return cookies


# ---------------------------------------------------------------------------
# Token & header fetching
# ---------------------------------------------------------------------------


def fetch_access_token(session_cookie: str) -> str:
    """Exchange the session cookie for a Bearer access token.

    Makes a GET request to the ChatGPT session endpoint using the
    project's :class:`~chatgpt_library_archiver.http_client.HttpClient`
    with redirects disabled to prevent leaking the session cookie.
    """
    from .http_client import HttpClient

    with HttpClient() as client:
        headers = {
            "Cookie": f"{_SESSION_COOKIE_NAME}={session_cookie}",
            "User-Agent": _DEFAULT_USER_AGENT,
        }
        session = client._get_session()
        resp = session.get(
            _SESSION_URL,
            headers=headers,
            timeout=client.timeout,
            allow_redirects=False,
        )
        if resp.status_code in (401, 403):
            msg = (
                "The ChatGPT session cookie appears to be expired or "
                "invalid. Please log into ChatGPT in your browser and "
                "try again."
            )
            raise SessionExpiredError(msg)
        if resp.status_code >= 400:  # noqa: PLR2004
            msg = f"Failed to fetch access token: HTTP {resp.status_code}"
            raise TokenFetchError(msg)
        try:
            data = resp.json()
        except Exception as exc:
            msg = "Session endpoint returned invalid JSON."
            raise TokenFetchError(msg) from exc

    token = data.get("accessToken")
    if not isinstance(token, str) or not token:
        msg = (
            "The session endpoint did not return an accessToken. "
            "The session cookie may be expired — log into ChatGPT "
            "in your browser and try again."
        )
        raise SessionExpiredError(msg)

    return token


def fetch_oai_headers(
    session_cookie: str,
    device_id: str | None = None,
) -> dict[str, str]:
    """Discover OAI-specific headers needed for API requests.

    *device_id* is used directly if provided; otherwise a fresh UUID is
    generated.  ``oai_client_version`` is fetched by loading the ChatGPT
    page and extracting the build manifest version.
    """
    oai_device_id = device_id or str(uuid.uuid4())
    oai_language = _OAI_LANGUAGE_DEFAULT

    # Attempt to scrape the client version from the ChatGPT page
    oai_client_version = _scrape_client_version(session_cookie)

    return {
        "oai_client_version": oai_client_version,
        "oai_device_id": oai_device_id,
        "oai_language": oai_language,
    }


def _scrape_client_version(session_cookie: str) -> str:
    """Best-effort extraction of the OAI client version from the page."""
    from .http_client import HttpClient

    with HttpClient() as client:
        headers = {
            "Cookie": f"{_SESSION_COOKIE_NAME}={session_cookie}",
            "User-Agent": _DEFAULT_USER_AGENT,
        }
        try:
            session = client._get_session()
            resp = session.get(
                _CHATGPT_PAGE_URL,
                headers=headers,
                timeout=client.timeout,
                allow_redirects=False,
            )
            html = resp.text
        except Exception:
            return ""

    # Common patterns: buildId in __NEXT_DATA__ or a version manifest
    # e.g. "buildId":"abc123..." or oai-client-version header hint
    for pattern in (
        r'"buildId"\s*:\s*"([^"]+)"',
        r"oai-client-version[\"']?\s*[:=]\s*[\"']([^\"']+)",
    ):
        match = re.search(pattern, html)
        if match:
            return match.group(1)

    return ""


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def extract_auth_config(browser: str = "edge") -> dict[str, str]:
    """Full extraction pipeline: cookies → token → auth config dict.

    Returns a dict whose keys match the ``auth.txt`` format consumed by
    :func:`~chatgpt_library_archiver.utils.load_auth_config`.
    """
    cookies = extract_cookies(browser)

    session_cookie = cookies.get(_SESSION_COOKIE_NAME)
    if not session_cookie:
        msg = (
            f"The '{_SESSION_COOKIE_NAME}' cookie was not found in "
            f"{_PROFILES[browser].name}. Make sure you are logged into "
            "ChatGPT at https://chatgpt.com in that browser."
        )
        raise SessionExpiredError(msg)

    access_token = fetch_access_token(session_cookie)

    device_id = cookies.get(_OAI_DID_COOKIE_NAME)
    oai_headers = fetch_oai_headers(session_cookie, device_id=device_id)

    user_agent = _DEFAULT_USER_AGENT

    return {
        "url": _AUTH_URL_DEFAULT,
        "authorization": f"Bearer {access_token}",
        "cookie": f"{_SESSION_COOKIE_NAME}={session_cookie}",
        "referer": _REFERER_DEFAULT,
        "user_agent": user_agent,
        **oai_headers,
    }


def write_auth_from_browser(
    browser: str = "edge",
    auth_path: str = "auth.txt",
) -> dict[str, str]:
    """Extract credentials from *browser* and write them to *auth_path*.

    The file is created with ``0o600`` permissions.  Returns the config
    dict that was written.
    """
    from .utils import write_secure_file

    config = extract_auth_config(browser)

    lines = "".join(f"{key}={value}\n" for key, value in config.items())
    write_secure_file(auth_path, lines)

    return config
