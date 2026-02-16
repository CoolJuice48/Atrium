# Contributing to Atrium

Thanks for your interest in contributing. This document covers how to run tests, format code, and submit changes.

## Prerequisites

- Python 3.10+
- Node.js 18+
- See [README.md](README.md) for full setup.

## Quick start

```bash
make setup    # Create venv, install Python + Node deps
make test     # Run all tests
make run      # Start backend + frontend
```

## Running tests

### Python (backend)

```bash
cd pdf_processor
source ../.venv/bin/activate   # or: .venv\Scripts\activate on Windows
python -m pytest tests/ -v
```

Or via Makefile:

```bash
make test
```

### Frontend typecheck (optional)

```bash
cd frontend
npm run build   # Runs TypeScript check
```

## Code style

- **Python**: Follow PEP 8. Use 4 spaces. No trailing whitespace.
- **TypeScript**: Use the project's existing style. Run `npm run build` to catch type errors.

## Pre-push check (optional)

Before your first push, run:

```bash
python scripts/check_clean_repo.py
```

This verifies you're not committing `textbook_index/`, large generated files, or other artifacts.

## Pull request guidelines

1. **Keep changes focused** – One logical change per PR.
2. **Tests must pass** – Run `make test` before submitting.
3. **No breaking changes** – Preserve existing behavior unless explicitly agreed.
4. **Determinism** – Avoid non-deterministic behavior in core logic.
5. **Don't touch `legacy/`** – Unless migrating or fixing critical bugs; avoid breaking imports.

## Project structure

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module overview.

## Questions?

Open an issue for discussion.
