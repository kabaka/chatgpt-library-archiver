import os

import pytest

from chatgpt_library_archiver import bootstrap


@pytest.fixture(autouse=True)
def restore_env(monkeypatch):
    # Ensure environment detection uses default values unless overridden
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    yield


def test_select_installer_prefers_uv(monkeypatch):
    env = bootstrap.EnvironmentInfo(
        prefix="/env",
        python="python",
        is_active=False,
        created=False,
    )

    def fake_find_executable(name, env_dir=None):
        if name == "uv":
            return "uv-bin"
        return None

    monkeypatch.setattr(bootstrap, "find_executable", fake_find_executable)
    assert bootstrap.select_installer(env) == ("uv", ("uv-bin", "pip", "sync"))


def test_select_installer_prefers_pip_tools(monkeypatch):
    env = bootstrap.EnvironmentInfo(
        prefix="/env",
        python="python",
        is_active=False,
        created=False,
    )

    def fake_find_executable(name, env_dir=None):
        if name == "pip-sync":
            return "pip-sync-bin"
        return None

    monkeypatch.setattr(bootstrap, "find_executable", fake_find_executable)
    assert bootstrap.select_installer(env) == ("pip-tools", ("pip-sync-bin",))


def test_select_installer_falls_back_to_pip(monkeypatch):
    env = bootstrap.EnvironmentInfo(
        prefix="/env",
        python="python",
        is_active=False,
        created=False,
    )
    monkeypatch.setattr(
        bootstrap,
        "find_executable",
        lambda *args, **kwargs: None,
    )
    assert bootstrap.select_installer(env) == (
        "pip",
        ("python", "-m", "pip", "install"),
    )


def test_install_dependencies_skips_missing_files(monkeypatch, capsys, tmp_path):
    env = bootstrap.EnvironmentInfo(
        prefix=str(tmp_path),
        python="python",
        is_active=False,
        created=False,
    )
    monkeypatch.setattr(
        bootstrap,
        "select_installer",
        lambda env: ("pip", ("python", "-m", "pip", "install")),
    )
    bootstrap.install_dependencies(env, [str(tmp_path / "missing.txt")])
    captured = capsys.readouterr()
    assert "No requirements files found" in captured.out


@pytest.mark.parametrize("tool", ["pip", "pip-tools", "uv"])
def test_install_dependencies_invokes_expected_command(monkeypatch, tmp_path, tool):
    env = bootstrap.EnvironmentInfo(
        prefix=str(tmp_path),
        python="py",
        is_active=False,
        created=False,
    )
    requirement = tmp_path / "requirements.txt"
    requirement.write_text("")

    if tool == "pip":
        expected_cmd = ["python", "-m", "pip", "install", "-r", str(requirement)]
        monkeypatch.setattr(
            bootstrap,
            "select_installer",
            lambda env: ("pip", ("python", "-m", "pip", "install")),
        )
    elif tool == "pip-tools":
        expected_cmd = ["pip-sync", str(requirement)]
        monkeypatch.setattr(
            bootstrap,
            "select_installer",
            lambda env: ("pip-tools", ("pip-sync",)),
        )
    else:  # uv
        expected_cmd = ["uv", "pip", "sync", str(requirement)]
        monkeypatch.setattr(
            bootstrap,
            "select_installer",
            lambda env: ("uv", ("uv", "pip", "sync")),
        )

    called = []
    monkeypatch.setattr(
        bootstrap.subprocess,
        "check_call",
        lambda cmd: called.append(cmd),
    )
    bootstrap.install_dependencies(env, [str(requirement)])
    assert called == [expected_cmd]


def test_ensure_environment_detects_active_virtualenv(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "in_venv", lambda: True)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))
    monkeypatch.setattr(bootstrap.sys, "executable", str(tmp_path / "python"))
    env = bootstrap.ensure_environment(str(tmp_path))
    assert env.is_active is True
    assert env.python == str(tmp_path / "python")
    assert env.prefix == str(tmp_path)


def test_ensure_environment_uses_project_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "in_venv", lambda: False)
    venv_dir = tmp_path / ".venv"
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True)
    python_path = bin_dir / ("python.exe" if os.name == "nt" else "python")
    python_path.write_text("")
    env = bootstrap.ensure_environment(str(tmp_path))
    assert env.is_active is False
    assert env.python == str(python_path)
    assert env.prefix == str(venv_dir)
