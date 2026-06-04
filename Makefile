.PHONY: setup run test clean help

PORT ?= 8080

help:
	@echo "Targets:"
	@echo "  make setup   - create venv and install dependencies"
	@echo "  make run     - start the web UI on http://localhost:$(PORT)"
	@echo "  make test    - run the automated test suite"
	@echo "  make clean   - remove venv and caches"

setup:
	uv venv .venv
	uv pip install -r requirements.txt
	@echo ""
	@echo "Setup complete. Run 'make run' to start the UI on http://localhost:$(PORT)"

run:
	uv run uvicorn src.app:app --host 0.0.0.0 --port $(PORT)

test:
	uv run pytest -q

clean:
ifeq ($(OS),Windows_NT)
	if exist .venv rd /s /q .venv
	if exist .pytest_cache rd /s /q .pytest_cache
	if exist runs rd /s /q runs
	if exist logs rd /s /q logs
else
	rm -rf .venv .pytest_cache __pycache__ src/__pycache__ src/**/__pycache__ tests/__pycache__ runs logs
endif
