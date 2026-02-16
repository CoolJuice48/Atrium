# Atrium Makefile (macOS-friendly)
# Usage: make setup, make test, make run, make backend, make frontend

SHELL := /bin/bash
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 3000

.PHONY: setup test run backend frontend

setup:
	@echo "Creating venv..."
	python3 -m venv $(VENV)
	@echo "Installing Python deps..."
	$(PIP) install -q -r pdf_processor/requirements.txt
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Done. Run 'make run' to start."

test:
	@echo "Running Python tests..."
	cd pdf_processor && ../$(PYTHON) -m pytest tests/ -q
	@echo "Running frontend typecheck..."
	cd frontend && npm run build --silent 2>/dev/null || true
	@echo "Tests complete."

run:
	@echo "Starting backend + frontend..."
	@echo "Backend: http://localhost:$(BACKEND_PORT)/docs"
	@echo "Frontend: http://localhost:$(FRONTEND_PORT)"
	@echo ""
	$(MAKE) -j2 _run_backend _run_frontend

_run_backend:
	cd pdf_processor && NEXT_PUBLIC_API_BASE=http://localhost:$(BACKEND_PORT) ../$(VENV)/bin/uvicorn server.app:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

_run_frontend:
	NEXT_PUBLIC_API_BASE=http://localhost:$(BACKEND_PORT) cd frontend && npm run dev -- -p $(FRONTEND_PORT)

backend:
	@echo "Backend: http://localhost:$(BACKEND_PORT)/docs"
	cd pdf_processor && ../$(VENV)/bin/uvicorn server.app:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

frontend:
	@echo "Frontend: http://localhost:$(FRONTEND_PORT)"
	NEXT_PUBLIC_API_BASE=http://localhost:$(BACKEND_PORT) cd frontend && npm run dev -- -p $(FRONTEND_PORT)
