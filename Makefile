.PHONY: test format typecheck lint check install

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r contracts/requirements.txt
	$(PYTHON) -m pip install -r backend/requirements.txt
	$(PYTHON) -m pip install -e backend

# Collects tests/ (healthz + skeleton) and contracts/ (0.4 schema checks).
test:
	$(PYTHON) -m pytest tests contracts

format:
	$(PYTHON) -m ruff format backend tests

lint:
	$(PYTHON) -m ruff check backend tests

typecheck:
	cd backend && $(PYTHON) -m mypy slove_context

check: format lint typecheck test
