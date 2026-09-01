.PHONY: all format lint type test tests integration_tests check_imports help

all: help

TEST_FILE ?= tests/unit_tests/
integration_test integration_tests: TEST_FILE = tests/integration_tests/

test tests:
	uv run --group test pytest -q $(TEST_FILE)

# Real CLI calls (claude.ai subscription); gated behind an env flag.
integration_test integration_tests:
	LANGCHAIN_CLAUDE_CODE_INTEGRATION=1 uv run --group test pytest -v --tb=short $(TEST_FILE)

PYTHON_FILES = .
lint:
	uv run --group lint ruff check $(PYTHON_FILES)
	uv run --group lint ruff format $(PYTHON_FILES) --diff

format:
	uv run --group lint ruff format $(PYTHON_FILES)
	uv run --group lint ruff check --fix $(PYTHON_FILES)

type:
	uv run --group typing --group test mypy langchain_claude_code

check_imports: $(shell find langchain_claude_code -name '*.py')
	uv run python ./scripts/check_imports.py $^

help:
	@echo '----'
	@echo 'check_imports        - check imports'
	@echo 'format               - run code formatters'
	@echo 'lint                 - run linters'
	@echo 'type                 - run mypy'
	@echo 'test                 - run unit tests (no CLI, no network)'
	@echo 'integration_tests    - run integration tests (real claude CLI)'
