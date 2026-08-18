.PHONY: test format typecheck check install

PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r contracts/requirements.txt

# Collects tests/ (1.1 placeholder) and contracts/ (0.4 schema checks).
test:
	$(PYTHON) -m pytest tests contracts

# Node 1.1 has no application modules to format or type-check.
format:
	@true

typecheck:
	@true

check: format typecheck test
