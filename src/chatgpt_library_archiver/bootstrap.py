from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .utils import prompt_yes_no


def in_venv() -> bool:
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


def venv_python(venv_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def venv_bin(venv_dir: str, executable: str) -> str:
    suffix = "Scripts" if os.name == "nt" else "bin"
    ext = ".exe" if os.name == "nt" and not executable.endswith(".exe") else ""
    return os.path.join(venv_dir, suffix, f"{executable}{ext}")


def find_executable(name: str, env_dir: str | None = None) -> str | None:
    candidates: list[str] = []
    if env_dir:
        candidate = venv_bin(env_dir, name)
        if os.path.isfile(candidate):
            candidates.append(candidate)
    found = shutil.which(name)
    if found:
        candidates.append(found)
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


@dataclass
class EnvironmentInfo:
    prefix: str
    python: str
    is_active: bool
    created: bool


def ensure_environment(project_root: str) -> EnvironmentInfo:
    venv_dir = os.path.join(project_root, ".venv")

    if in_venv():
        prefix = os.environ.get("VIRTUAL_ENV") or sys.prefix
        return EnvironmentInfo(
            prefix=prefix, python=sys.executable, is_active=True, created=False
        )

    created = False
    if not os.path.isdir(venv_dir):
        print("No virtual environment found (.venv).")
        if prompt_yes_no("Create one and install requirements now?"):
            print("Creating virtual environment...")
            subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
            created = True
        else:
            print(
                "Aborting. Please create a venv and install requirements to continue."
            )
            sys.exit(1)

    py_exe = venv_python(venv_dir)
    if not os.path.isfile(py_exe):
        print(
            "Python executable inside .venv not found. "
            "The virtual environment may be broken."
        )
        sys.exit(1)

    return EnvironmentInfo(
        prefix=venv_dir, python=py_exe, is_active=False, created=created
    )


def select_installer(env: EnvironmentInfo) -> tuple[str, Sequence[str]]:
    uv = find_executable("uv", env.prefix)
    if uv:
        return "uv", (uv, "pip", "sync")

    pip_sync = find_executable("pip-sync", env.prefix)
    if pip_sync:
        return "pip-tools", (pip_sync,)

    # Fallback to the environment's python -m pip install
    return "pip", (env.python, "-m", "pip", "install")


def install_dependencies(env: EnvironmentInfo, requirements: Iterable[str]) -> None:
    reqs = [req for req in requirements if os.path.isfile(req)]
    if not reqs:
        print("No requirements files found; skipping dependency installation.")
        return

    installer_name, base_cmd = select_installer(env)
    if installer_name == "pip":
        cmd: list[str] = list(base_cmd)
        for req in reqs:
            cmd.extend(["-r", req])
    else:
        cmd = list(base_cmd) + reqs

    print(f"Installing dependencies using {installer_name}...")
    subprocess.check_call(cmd)


def main(tag_new: bool = False):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    env = ensure_environment(project_root)

    requirements = [
        os.path.join(project_root, "requirements.txt"),
        os.path.join(project_root, "requirements-dev.txt"),
    ]
    install_dependencies(env, requirements)

    print("Launching chatgpt_library_archiver inside the virtual environment...")
    cmd = [env.python, "-m", "chatgpt_library_archiver"]
    if tag_new:
        cmd.append("--tag-new")
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
