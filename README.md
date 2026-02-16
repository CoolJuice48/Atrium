# Atrium

Atrium turns your textbooks into an interactive study system.

Ask questions. Generate evidence-backed answers. Convert them into flashcards. Track mastery over time.

Bring your own PDFs or use open-licensed materials.

- **Ask** – Query your indexed textbooks (offline TF-IDF search)
- **Study** – Flashcards, study plans, and adaptive review
- **Progress** – Mastery tracking by book and section

Atrium does not:
- Ship copyrighted textbooks
- Replace your course materials
- Guarantee correctness of AI-generated summaries

BETA NOTICE:
Atrium is under active development. The interface and features may change. Please report issues or suggestions via GitHub Issues.


## Quickstart
Requirements: Python 3.10+ and Node 18+

```bash
make setup
make run
```

**First run**: Put PDFs in `./pdfs`, then either:
- `make run-bootstrap` — builds the index if missing, then starts the app
- Or `make run` and click **Build Index** in the UI

Then open:
- **App**: http://localhost:3000
- **API docs**: http://localhost:8000/docs

## Screenshots

<!-- Add screenshots here -->
*[Screenshot: Ask panel]*
*[Screenshot: Study panel]*
*[Screenshot: Progress panel]*

## Adding books

Atrium does **not** ship with textbook content. You provide your own.

1. Place your PDFs in `pdfs/`
2. Run `make run-bootstrap` (builds index if missing, then starts app), or `make run` and click **Build Index** in the UI
3. Or run `make index` manually, then `make run`

For full pipeline (Q&A extraction, question banks), use `python run_pipeline.py` (see [docs/USAGE.md](docs/USAGE.md)).

**Content policy**: Use only content you have rights to — Creative Commons, public domain, or your own materials. No copyrighted textbooks are included.

## Project structure

| Path | Description |
|------|-------------|
| `server/`, `study/`, `graph/`, `rag/`, `legacy/` | Backend (FastAPI, Python) |
| `frontend/` | Next.js app |
| `docs/` | Architecture, usage, dev guides |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Hosting packs from your PC

Atrium Packs are modular curriculum bundles (open-licensed only). To host packs locally:

1. Run the packs CLI build:
   ```bash
   python scripts/packs_cli.py build
   ```
2. Serve the dist folder:
   ```bash
   cd atrium_packs/dist && python -m http.server 7777
   ```
3. Configure the frontend:
   ```
   NEXT_PUBLIC_PACKS_BASE=http://localhost:7777
   ```

See [docs/packs/SCHEMA.md](docs/packs/SCHEMA.md) for pack manifest format.

## Docs

- [Usage](docs/USAGE.md) – End-user guide
- [Developer guide](docs/DEV.md) – Setup, tests, commands
- [Contributing](CONTRIBUTING.md) – PR guidelines

## License

MIT – see [LICENSE](LICENSE).
# Atrium
