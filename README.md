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

Put PDFs in `./pdfs` and `make run` will auto-build the search index if it doesn't exist. Or run `make index` manually.

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
2. Run `make run` — the index is built automatically from `pdfs/` if missing.
3. Or run `make index` manually, then `make run`.
4. For full pipeline (Q&A extraction, question banks), use `python run_pipeline.py` (see [docs/USAGE.md](docs/USAGE.md)).

**Content policy**: Use only content you have rights to (your notes, public domain, or licensed materials). No copyrighted textbooks are included.

## Project structure

| Path | Description |
|------|-------------|
| `server/`, `study/`, `graph/`, `rag/`, `legacy/` | Backend (FastAPI, Python) |
| `frontend/` | Next.js app |
| `docs/` | Architecture, usage, dev guides |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Docs

- [Usage](docs/USAGE.md) – End-user guide
- [Developer guide](docs/DEV.md) – Setup, tests, commands
- [Contributing](CONTRIBUTING.md) – PR guidelines

## License

MIT – see [LICENSE](LICENSE).
# Atrium
