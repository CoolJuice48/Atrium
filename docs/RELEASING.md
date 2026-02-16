# Releasing Atrium

Instructions for preparing and publishing Atrium as a GitHub repository.

## Recommended repo name

`atrium` or `atrium-study` – short, memorable, no conflicts.

## What to include

- All source: `server/`, `study/`, `graph/`, `rag/`, `legacy/`, `extractors/`, `eval/`, `tests/`, `scripts/`, `frontend/`, `docs/`
- Config: `Makefile`, `.env.example`, `.gitignore`, `LICENSE`
- Docs: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`

## What to exclude (verify before push)

Run `python scripts/check_clean_repo.py` before first push.

- `textbook_index/` – generated indexes
- `converted/`, `pdfs/` – user content
- `.venv/`, `node_modules/`, `frontend/.next/`
- `*.pkl`, `*.faiss` – embeddings/index artifacts
- Large JSONL outputs (except `eval/golden_sets/`)

## Steps to initialize and push

1. Create a new repo on GitHub (no README, no .gitignore).
2. Locally:
   ```bash
   git init
   git add .
   python scripts/check_clean_repo.py   # Verify clean tree
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<user>/atrium.git
   git push -u origin main
   ```

## Release tags

Use semantic versioning: `v0.1.0`, `v0.2.0`, etc.

```bash
git tag -a v0.1.0 -m "Release 0.1.0"
git push origin v0.1.0
```

## Minimal demo index (CC content)

To ship a small demo index with CC-licensed content:

1. Find a short CC-licensed text (e.g. public domain excerpt).
2. Convert to the expected format (chunks_content.jsonl or equivalent).
3. Build a minimal index via `scripts/build_index.py` or the pipeline.
4. Place in `textbook_index/demo/` and document in README.
5. Ensure LICENSE and attribution are clear.

Do **not** include copyrighted textbooks.
