import os
import tempfile

from chatgpt_library_archiver.utils import (
    load_auth_config,
    ensure_auth_config,
    prompt_yes_no,
)


def write_auth(tmpdir, content: str):
    path = os.path.join(tmpdir, 'auth.txt')
    with open(path, 'w', encoding='utf-8') as f:
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
        assert cfg['url'] == 'https://example.com'
        assert cfg['authorization'].startswith('Bearer ')
        assert 'session-token' in cfg['cookie']


def test_ensure_auth_config_raises_on_missing_when_user_declines(monkeypatch):
    # Simulate user declining to create file
    inputs = iter(['n'])
    monkeypatch.setattr('builtins.input', lambda _: next(inputs))

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'auth.txt')
        try:
            ensure_auth_config(path)
            raised = False
        except FileNotFoundError:
            raised = True
        assert raised


def test_prompt_yes_no_respects_defaults(monkeypatch):
    # default True when user presses enter
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert prompt_yes_no('continue?') is True

    # default False when user presses enter
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert prompt_yes_no('continue?', default=False) is False


def test_prompt_yes_no_parses_input(monkeypatch):
    inputs = iter(['y', 'n'])
    monkeypatch.setattr('builtins.input', lambda _: next(inputs))
    assert prompt_yes_no('q?', default=False) is True
    assert prompt_yes_no('q?', default=True) is False


def test_prompt_yes_no_autoconfirm(monkeypatch):
    monkeypatch.setenv('ARCHIVER_ASSUME_YES', '1')
    # Should return True without prompting
    assert prompt_yes_no('skip?') is True

