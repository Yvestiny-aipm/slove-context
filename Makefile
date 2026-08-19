.PHONY: test format typecheck lint check install migrate frontend-test demo

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
# Agent registry / permissions + single-scene DAG + batch schedule +
# node 9.1 narrative consistency evals + node 9.2 experiment runs +
# node 9.3 release gates / book export + node UI.1 demo seeder / CORS +
# node UI.2 human shuttle)
# and contracts/ (0.4). No live Postgres and no real model calls.
test:
	$(PYTHON) -m pytest tests contracts

# Headless vitest + testing-library. No live model. No browser window.
frontend-test:
	cd frontend && npm test

# Seed Fake Provider Demo in-process and start backend + Vite UI.
# Open http://127.0.0.1:5173 — not a production service.
demo:
	$(PYTHON) -m slove_context.demo --host 127.0.0.1 --port 8000 --with-frontend

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
