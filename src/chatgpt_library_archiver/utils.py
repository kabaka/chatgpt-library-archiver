from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import TypedDict, cast

REQUIRED_AUTH_KEYS = [
    "url",
    "authorization",
    "cookie",
    "referer",
    "user_agent",
    "oai_client_version",
    "oai_device_id",
    "oai_language",
]

_SENSITIVE_AUTH_KEYS: frozenset[str] = frozenset({"authorization", "cookie"})


class AuthConfig(TypedDict):
    """Typed dictionary for authentication configuration values."""

    url: str
    authorization: str
    cookie: str
    referer: str
    user_agent: str
    oai_client_version: str
    oai_device_id: str
    oai_language: str


# Environment variable to automatically answer yes to prompts
ASSUME_YES_ENV = "ARCHIVER_ASSUME_YES"


def prompt_yes_no(message: str, default: bool = True) -> bool:
    """Prompt the user with a yes/no question.

    If ``ARCHIVER_ASSUME_YES`` is set to a truthy value (``1``, ``true``,
    ``yes``), the prompt is bypassed and ``True`` is returned immediately.

    Args:
        message: The question to display to the user.
        default: The return value if the user just hits enter.

    Returns:
        ``True`` for yes and ``False`` for no.
    """

    assume = os.environ.get(ASSUME_YES_ENV, "").lower()
    if assume in {"1", "true", "yes"}:
        print(f"{message} [Y/n]: y (auto)")
        return True

    prompt = f"{message} [{'Y/n' if default else 'y/N'}]: "
    while True:
        choice = input(prompt).strip().lower()
        if not choice:
            return default
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'.")


def mask_sensitive(value: str, visible: int = 8) -> str:
    """Return a masked version of *value* showing only the first *visible* chars.

    Used to provide a confirmation hint after accepting sensitive input
    without exposing the full secret.
    """
    if len(value) <= visible:
        return value
    return value[:visible] + "..."


def write_secure_file(path: str | Path, content: str, mode: int = 0o600) -> None:
    """Write *content* to *path* with restricted file permissions.

    Uses ``os.open`` with an explicit *mode* so the file is never
    world-readable, even briefly.  The default mode ``0o600`` restricts
    access to the file owner.  Permissions are also enforced on
    pre-existing files via :func:`os.chmod`.
    """

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(str(path), mode)
    except BaseException:
        # fd is already consumed by os.fdopen; nothing extra to close.
        raise


def load_auth_config(path: str = "auth.txt") -> AuthConfig:
    """Load key=value lines from auth.txt into a dict.
    Ignores lines without '=' and whitespace-only lines.
    """
    config: dict[str, str] = {}
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    with Path(path).open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    return cast(AuthConfig, config)


def prompt_and_write_auth(path: str = "auth.txt") -> AuthConfig:
    print("\nAuth file not found or invalid. Let's create it.\n")
    print("Instructions: In your browser, open Developer Tools → Network,")
    print("find a request to 'image_gen', and copy these exact header values.\n")

    cfg: dict[str, str] = {}
    for key in REQUIRED_AUTH_KEYS:
        sensitive = key in _SENSITIVE_AUTH_KEYS
        while True:
            if sensitive:
                val = getpass.getpass(f"{key} = ").strip()
            else:
                val = input(f"{key} = ").strip()
            if val:
                cfg[key] = val
                if sensitive:
                    print(f"  \u2713 {key} set: {mask_sensitive(val)}")
                break
            else:
                print("This field is required. Please enter a value.")

    lines = "".join(f"{k}={cfg[k]}\n" for k in REQUIRED_AUTH_KEYS)
    write_secure_file(path, lines)

    print(f"\nSaved credentials to {path}.\n")
    return cast(AuthConfig, cfg)


def ensure_auth_config(path: str = "auth.txt") -> AuthConfig:
    try:
        cfg = load_auth_config(path)
    except FileNotFoundError:
        if prompt_yes_no("auth.txt not found. Create it now?"):
            cfg = prompt_and_write_auth(path)
        else:
            raise

    # Basic validation
    missing = [k for k in REQUIRED_AUTH_KEYS if not cfg.get(k)]
    if missing:
        msg = "auth.txt is missing required keys. Re-enter credentials now?"
        if prompt_yes_no(msg):
            cfg = prompt_and_write_auth(path)
        else:
            raise ValueError("auth.txt is missing required keys")

    return cfg
