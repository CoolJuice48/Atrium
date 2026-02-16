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

1. Place your PDFs in:
   pdf_processor/pdfs/

2. From the repo root, run:
   make backend
   cd pdf_processor
   python run_pipeline.py

3. Or use the minimal demo index (see [docs/USAGE.md](docs/USAGE.md))

**Content policy**: Use only content you have rights to (your notes, public domain, or licensed materials). No copyrighted textbooks are included.

## Project structure

| Path | Description |
|------|-------------|
| `pdf_processor/` | Backend (FastAPI, Python) |
| `frontend/` | Next.js app |
| `docs/` | Architecture, usage, dev guides |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Docs

- [Usage](docs/USAGE.md) – End-user guide
- [Developer guide](docs/DEV.md) – Setup, tests, commands
- [Contributing](CONTRIBUTING.md) – PR guidelines

## License

MIT – see [LICENSE](LICENSE).
