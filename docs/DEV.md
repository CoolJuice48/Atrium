# Developer Guide

Steps for developers working on Atrium.

## Setup

```bash
make setup
```

This:
- Creates `.venv` and installs Python deps (`pdf_processor/requirements.txt`)
- Runs `npm install` in `frontend/`

## Running locally

```bash
make run
```

Starts backend (port 8000) and frontend (port 3000) concurrently.

Or run separately:

```bash
make backend   # uvicorn server.app:app --reload --port 8000
make frontend # cd frontend && npm run dev
```

## Tests

```bash
make test
```

Runs:
- `python -m pytest tests/` (from `pdf_processor/`)
- Optional: `npm run build` in frontend (TypeScript check)

## Common commands

| Command | Description |
|---------|-------------|
| `make setup` | Create venv, install deps |
| `make test` | Run Python tests |
| `make run` | Start backend + frontend |
| `make backend` | Start backend only |
| `make frontend` | Start frontend only |

## Python

- **CWD**: Run server/tests from `pdf_processor/` (or set `PYTHONPATH`)
- **Venv**: `.venv` at repo root
- **Tests**: `python -m pytest tests/ -v`

## Frontend

- **CWD**: `frontend/`
- **API base**: `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`)

## Ports

- Backend: 8000
- Frontend: 3000

If ports are in use, the dev runner will report an error. Stop the conflicting process or change ports via env (see scripts).
