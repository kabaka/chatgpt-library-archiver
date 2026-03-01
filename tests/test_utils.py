import os
import stat
import tempfile

import pytest

from chatgpt_library_archiver.utils import (
    _SENSITIVE_AUTH_KEYS,
    REQUIRED_AUTH_KEYS,
    ensure_auth_config,
    load_auth_config,
    mask_sensitive,
    prompt_and_write_auth,
    prompt_yes_no,
    write_secure_file,
)

EXPECTED_AUTH_MODE = 0o600


def write_auth(tmpdir, content: str):
    path = os.path.join(tmpdir, "auth.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_load_auth_config_parses_key_values():
    with tempfile.TemporaryDirectory() as d:
        path = write_auth(
            d,
            """
url=https://example.com
authorization=Bearer abc
cookie=__Secure-next-auth.session-token=xyz
referer=https://chat.openai.com/library
user_agent=Mozilla/5.0
oai_client_version=1.0
oai_device_id=dev123
oai_language=en-US
""".strip(),
        )

        cfg = load_auth_config(path)
        assert cfg["url"] == "https://example.com"
        assert cfg["authorization"].startswith("Bearer ")
        assert "session-token" in cfg["cookie"]


def test_ensure_auth_config_raises_on_missing_when_user_declines(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "auth.txt")
        try:
            ensure_auth_config(path)
            raised = False
        except FileNotFoundError:
            raised = True
        assert raised


def test_ensure_auth_config_rejects_partial_config(monkeypatch):
    inputs = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with tempfile.TemporaryDirectory() as d:
        path = write_auth(d, "url=https://example.com\n")
        with pytest.raises(ValueError) as exc:
            ensure_auth_config(path)
        assert "required keys" in str(exc.value)


def test_prompt_and_write_auth_sets_strict_permissions(monkeypatch):
    nonsensitive_keys = [k for k in REQUIRED_AUTH_KEYS if k not in _SENSITIVE_AUTH_KEYS]
    sensitive_keys = [k for k in REQUIRED_AUTH_KEYS if k in _SENSITIVE_AUTH_KEYS]
    nonsensitive_iter = iter([f"val_{k}" for k in nonsensitive_keys])
    sensitive_iter = iter([f"val_{k}" for k in sensitive_keys])
    monkeypatch.setattr("builtins.input", lambda _: next(nonsensitive_iter))
    monkeypatch.setattr(
        "chatgpt_library_archiver.utils.getpass.getpass",
        lambda _: next(sensitive_iter),
    )

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "auth.txt")
        cfg = prompt_and_write_auth(path)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == EXPECTED_AUTH_MODE
        assert cfg["url"] == "val_url"


def test_prompt_yes_no_respects_defaults(monkeypatch):
    # default True when user presses enter
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert prompt_yes_no("continue?") is True

    # default False when user presses enter
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert prompt_yes_no("continue?", default=False) is False


def test_prompt_yes_no_parses_input(monkeypatch):
    inputs = iter(["y", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    assert prompt_yes_no("q?", default=False) is True
    assert prompt_yes_no("q?", default=True) is False


def test_prompt_yes_no_autoconfirm(monkeypatch):
    monkeypatch.setenv("ARCHIVER_ASSUME_YES", "1")
    # Should return True without prompting
    assert prompt_yes_no("skip?") is True


def test_write_secure_file_sets_permissions(tmp_path):
    path = tmp_path / "secret.json"
    write_secure_file(path, '{"key": "value"}')
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == EXPECTED_AUTH_MODE
    assert path.read_text(encoding="utf-8") == '{"key": "value"}'


def test_write_secure_file_overwrites_existing(tmp_path):
    path = tmp_path / "overwrite.txt"
    path.write_text("old content")
    write_secure_file(path, "new content")
    assert path.read_text(encoding="utf-8") == "new content"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == EXPECTED_AUTH_MODE


def test_write_secure_file_custom_mode(tmp_path):
    path = tmp_path / "custom.txt"
    write_secure_file(path, "data", mode=0o640)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o640


# --- mask_sensitive tests ---


def test_mask_sensitive_truncates_long_value():
    assert mask_sensitive("sk-Zpp16abcdef1234567890") == "sk-Zpp16..."


def test_mask_sensitive_returns_short_value_unchanged():
    assert mask_sensitive("short") == "short"
    assert mask_sensitive("exactly8") == "exactly8"


def test_mask_sensitive_custom_visible():
    assert mask_sensitive("abcdefghij", visible=4) == "abcd..."


# --- getpass usage for sensitive auth keys ---


def test_prompt_and_write_auth_uses_getpass_for_sensitive_keys(monkeypatch, capsys):
    """getpass.getpass must be called for authorization and cookie keys."""
    getpass_calls = []

    def fake_getpass(prompt):
        getpass_calls.append(prompt)
        return f"secret-for-{prompt.split()[0]}"

    nonsensitive_iter = iter(
        [f"val_{k}" for k in REQUIRED_AUTH_KEYS if k not in _SENSITIVE_AUTH_KEYS]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(nonsensitive_iter))
    monkeypatch.setattr("chatgpt_library_archiver.utils.getpass.getpass", fake_getpass)

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "auth.txt")
        cfg = prompt_and_write_auth(path)

    # Verify getpass was called for exactly the sensitive keys
    assert len(getpass_calls) == len(_SENSITIVE_AUTH_KEYS)
    for key in _SENSITIVE_AUTH_KEYS:
        assert any(key in call for call in getpass_calls)

    # Verify masked confirmation was printed
    out = capsys.readouterr().out
    for key in _SENSITIVE_AUTH_KEYS:
        assert f"\u2713 {key} set:" in out

    # Verify sensitive values were stored
    assert cfg["authorization"].startswith("secret-for-")
    assert cfg["cookie"].startswith("secret-for-")
