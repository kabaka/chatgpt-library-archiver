from pathlib import Path


def test_pre_commit_hook_runs_lint_and_tests():
    hook_path = Path(__file__).resolve().parent.parent / ".githooks" / "pre-commit"
    content = hook_path.read_text()
    assert "make lint" in content
    assert "make test" in content
