.PHONY: install lint test build

install:
	python -m pip install -e .[dev]
	pre-commit install --install-hooks

lint:
	pre-commit run --all-files

test:
        python -m pytest

build:
	python -m build
