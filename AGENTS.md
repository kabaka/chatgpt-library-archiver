# Repository Instructions

- Before committing changes in this repository, run `pre-commit run --all-files` and address any issues it reports.
- Install the development dependencies (for example, `pip install -e .[dev]` or `make install`) so tools like `pre-commit`, `ruff`, and the rest of the automation are available on your `PATH`.
- Configure Git to use the repository's hooks with `git config core.hooksPath .githooks`.
- The provided Git hook runs `make lint` and `make test`, matching the guidance in the README.
