from pathlib import Path

import yaml


def test_pre_commit_config_includes_ruff_hooks():
    config_path = Path(__file__).resolve().parent.parent / ".pre-commit-config.yaml"
    config = yaml.safe_load(config_path.read_text())
    hook_ids = [hook["id"] for repo in config["repos"] for hook in repo["hooks"]]
    assert "ruff-check" in hook_ids
    assert "ruff-format" in hook_ids


def test_pre_commit_ruff_hooks_use_system_language():
    config_path = Path(__file__).resolve().parent.parent / ".pre-commit-config.yaml"
    config = yaml.safe_load(config_path.read_text())
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            if hook["id"] in ("ruff-check", "ruff-format"):
                assert hook["language"] == "system", (
                    f"Hook {hook['id']} should use language: system"
                )
