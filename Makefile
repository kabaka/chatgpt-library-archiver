.PHONY: install lint test build deps deps-pip deps-pip-tools deps-uv

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
	python -m pre_commit run --all-files

test:
	python -m pytest

build:
	python -m build
