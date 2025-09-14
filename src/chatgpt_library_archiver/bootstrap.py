import os
import sys
import subprocess
import shutil

from .utils import prompt_yes_no


def in_venv() -> bool:
    return (
        hasattr(sys, 'real_prefix') or
        (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    )


def venv_python(venv_dir: str) -> str:
    if os.name == 'nt':
        return os.path.join(venv_dir, 'Scripts', 'python.exe')
    return os.path.join(venv_dir, 'bin', 'python')


def venv_pip(venv_dir: str) -> str:
    if os.name == 'nt':
        return os.path.join(venv_dir, 'Scripts', 'pip.exe')
    return os.path.join(venv_dir, 'bin', 'pip')


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_dir = os.path.join(project_root, '.venv')

    # Create venv if missing
    if not os.path.isdir(venv_dir):
        print('No virtual environment found (.venv).')
        if prompt_yes_no('Create one and install requirements now?'):
            print('Creating virtual environment...')
            subprocess.check_call([sys.executable, '-m', 'venv', venv_dir])
        else:
            print('Aborting. Please create a venv and install requirements to continue.')
            sys.exit(1)

    # Install requirements
    pip_exe = venv_pip(venv_dir)
    if not os.path.isfile(pip_exe):
        print('pip inside venv not found. The venv may be broken.')
        sys.exit(1)

    req_path = os.path.join(project_root, 'requirements.txt')
    if os.path.isfile(req_path):
        print('Installing requirements...')
        subprocess.check_call([pip_exe, 'install', '-r', req_path])
    else:
        print('requirements.txt not found; skipping dependency installation.')

    # Re-run package CLI inside venv
    py_exe = venv_python(venv_dir)
    print('Launching chatgpt_library_archiver inside the virtual environment...')
    sys.exit(subprocess.call([py_exe, '-m', 'chatgpt_library_archiver']))


if __name__ == '__main__':
    main()

