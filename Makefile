.PHONY: install test build

install:
	python -m pip install -e .[dev]

test:
	python -m pytest

build:
	python -m build
