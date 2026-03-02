.PHONY: install lint test build deps deps-pip deps-pip-tools deps-uv clean fmt check

SYNC_REQUIREMENTS = requirements.txt requirements-dev.txt

install: deps
	python -m pre_commit install --install-hooks

deps: deps-pip

deps-pip:
	python -m pip install -e .[dev]

deps-pip-tools:
	pip-sync $(SYNC_REQUIREMENTS)
	python -m pip install -e . --no-deps

deps-uv:
	uv pip sync $(SYNC_REQUIREMENTS)
	uv pip install -e . --no-deps

lint:
	python -m ruff check .
	python -m ruff format --check .
	python -m pyright

test:
	python -m pytest --cov=chatgpt_library_archiver --cov-report=term-missing --cov-fail-under=85

build:
	python -m build

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf .coverage htmlcov/

fmt:
	python -m ruff check --fix .
	python -m ruff format .

check: lint test
