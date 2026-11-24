.PHONY: test cov lint format typecheck check docs

PYTHONPATH ?= src

test:
	PYTHONPATH=$(PYTHONPATH) pytest -v

cov:
	PYTHONPATH=$(PYTHONPATH) pytest --cov=maintnote --cov-report=term-missing

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff format src tests

typecheck:
	MYPYPATH=$(PYTHONPATH) mypy src

check: lint typecheck test

docs:
	mkdocs build --strict
