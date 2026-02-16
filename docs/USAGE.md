# Atrium Usage

End-user guide for running and using Atrium.

## Quick start

```bash
make setup
make run
```

Then open:
- **Frontend**: http://localhost:3000
- **API docs**: http://localhost:8000/docs

## Adding books

Atrium does **not** ship with textbook content. You provide your own materials.

### Option 1: Use the pipeline (PDF → index)

1. Place PDFs in `pdfs/`
2. Run the pipeline:
   ```bash
   source .venv/bin/activate
   python run_pipeline.py
   ```
3. Choose **[P] Process** and follow the menu to convert, classify, build corpus, and embed.

### Option 2: Minimal demo index (tests)

The tests build a minimal 3-doc index. For a quick demo:

1. Run the server; it will use `textbook_index/` if present.
2. If `textbook_index/` is empty, the `/catalog` and `/query` endpoints will return empty or error until you add content via the pipeline.

### Content policy

- Use only content you have rights to (e.g. your own notes, public domain, or licensed materials).
- No copyrighted textbooks are included by default.

## Using the app

### Ask panel
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
