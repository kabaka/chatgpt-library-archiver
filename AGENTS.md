# Repository Instructions

## Getting Started

- **Python ≥ 3.10** is required (`requires-python = ">=3.10"` in `pyproject.toml`).
- Install the development dependencies (for example, `pip install -e .[dev]` or
  `make install`) so tools like `pre-commit`, `ruff`, and the rest of the
  automation are available on your `PATH`.

## Quality Gates

- Before committing changes in this repository, run `pre-commit run --all-files`
  and address any issues it reports.
- Run `make lint` and `make test` before pushing changes.
- `make test` enforces a minimum **85 %** project-level test coverage via
  `--cov-fail-under=85`.

## Skill Files

Specialised guidance for AI agents lives in `.github/skills/`. Each
sub-directory contains a `SKILL.md` covering a specific domain (testing
strategy, HTTP resilience, image pipeline, OpenAI vision API, credential
handling, ADR workflow, gallery HTML patterns). Consult the relevant skill
before working in that area.

## Security-Sensitive Files

The following files contain secrets and **must never be committed** to version
control (they are already listed in `.gitignore`):

- `auth.txt` — ChatGPT session credentials
- `tagging_config.json` — OpenAI API key and tagging configuration
