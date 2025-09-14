import os
import tempfile

from utils import load_auth_config, ensure_auth_config


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

