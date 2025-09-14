.PHONY: install lint test build

install:
        python -m pip install -e .[dev]

lint:
	pre-commit run --all-files

test:
        python -m pytest

build:
	python -m build
