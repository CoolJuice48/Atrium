# Atrium Usage

End-user guide for running and using Atrium.

## Quick start

```bash
make setup
make run
```

**First run**: Put PDFs in `./pdfs`, then either:
- `make run-bootstrap` — builds the index if missing, then starts the app
- Or `make run` and click **Build Index** in the UI

Then open:
- **Frontend**: http://localhost:3000
- **API docs**: http://localhost:8000/docs

## Adding books

Atrium does **not** ship with textbook content. You provide your own materials.

### Option 1: Build Index (recommended)

1. Place PDFs in `pdfs/`
2. Run `make run-bootstrap` (builds index if missing, then starts app), or `make run` and click **Build Index** in the UI
3. Or run `make index` manually, then `make run`

### Option 2: Full pipeline (Q&A, question banks)

1. Place PDFs in `pdfs/`
2. Run the pipeline:
   ```bash
   source .venv/bin/activate
   python run_pipeline.py
   ```
3. Choose **[P] Process** and follow the menu to convert, classify, build corpus, and embed.

### Option 3: Minimal demo index (tests)

The tests build a minimal 3-doc index. For a quick demo:

1. Run the server; it will use `textbook_index/` if present.
2. If `textbook_index/` is empty and no PDFs are in `pdfs/`, the `/catalog` and `/query` endpoints will return empty until you add PDFs and run `make index` (or `make run`).

### Content policy

- Use only content you have rights to — Creative Commons, public domain, or your own materials.
- No copyrighted textbooks are included by default.

## Using the app

### Ask panel
- If no index exists, the panel shows "No index yet. Build it to ask questions." Use the Build Index panel above.
- Type a question and click **Ask**
- Optionally filter by book
- After an answer, click **Generate study cards from answer** to create flashcards

### Study panel
- Set minutes and click **Get plan** for a study plan
- **Refresh due** to load due cards
- Click **Review** on a card, type your answer, and submit

### Progress panel
- View overall mastery, total cards, due count
- See mastery by book and weakest sections
