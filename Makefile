.PHONY: test format typecheck lint check install migrate

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r contracts/requirements.txt
	$(PYTHON) -m pip install -r backend/requirements.txt
	$(PYTHON) -m pip install -e backend

# Collects tests/ (healthz + request_id + audit + story + canon + snapshot +
# scene + llm gateway + scene plan / scene draft / candidate extract +
# human approve / submit + scene / chapter summaries + validation run +
# repair task + context pack + outline revision + style guide / sample +
# style validation + review queue + local job queue / Worker +
# Agent registry / permissions + single-scene DAG)
# and contracts/ (0.4). No live Postgres and no real model calls.
test:
	$(PYTHON) -m pytest tests contracts

format:
	$(PYTHON) -m ruff format backend tests

lint:
	$(PYTHON) -m ruff check backend tests

typecheck:
	cd backend && $(PYTHON) -m mypy slove_context

# Optional. Needs local Postgres. Unit tests do not run this.
migrate:
	cd backend && $(PYTHON) -m alembic upgrade head

check: format lint typecheck test
