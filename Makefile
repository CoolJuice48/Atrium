PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

FRONTEND_DIR := frontend
INDEX_ROOT ?= textbook_index
PDF_DIR ?= pdfs

index:
	@if [ -f "$(INDEX_ROOT)/data.json" ]; then \
		echo "Index present: $(INDEX_ROOT)"; \
		exit 0; \
	fi; \
	PDF_COUNT=$$(find "$(PDF_DIR)" -maxdepth 1 -name "*.pdf" 2>/dev/null | wc -l); \
	if [ "$$PDF_COUNT" -eq 0 ]; then \
		echo "No PDFs found. Add PDFs to ./$(PDF_DIR) then run \`make index\` or \`make run\`."; \
		exit 1; \
	fi; \
	$(VENV)/bin/python scripts/bootstrap_index.py --pdf-dir "$(PDF_DIR)" --index-root "$(INDEX_ROOT)"

setup:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install --upgrade pip
	. $(VENV)/bin/activate && pip install -r requirements.txt
	cd $(FRONTEND_DIR) && npm install

backend:
	INDEX_ROOT=$(INDEX_ROOT) . $(VENV)/bin/activate && uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd $(FRONTEND_DIR) && npm run dev

run: index
	@echo "Starting Atrium..."
	@echo "Frontend: http://localhost:3000"
	@echo "API Docs: http://localhost:8000/docs"
	@make -j2 backend frontend

test:
	$(VENV)/bin/python -m pytest tests/ -q
