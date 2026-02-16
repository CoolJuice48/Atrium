PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

FRONTEND_DIR := frontend

setup:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install --upgrade pip
	. $(VENV)/bin/activate && pip install -r requirements.txt
	cd $(FRONTEND_DIR) && npm install

backend:
	. $(VENV)/bin/activate && uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd $(FRONTEND_DIR) && npm run dev

run:
	@echo "Starting Atrium..."
	@echo "Frontend: http://localhost:3000"
	@echo "API Docs: http://localhost:8000/docs"
	@make -j2 backend frontend

test:
	$(VENV)/bin/python -m pytest tests/ -q
