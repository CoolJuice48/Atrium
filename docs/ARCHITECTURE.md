# Atrium Architecture

High-level overview of the codebase modules.

## Directory layout

```
Atrium/
├── pdf_processor/          # Backend (Python)
│   ├── server/            # FastAPI API
│   ├── legacy/            # PDF extraction, search (TF-IDF)
│   ├── extractors/        # PDF backends (PyMuPDF)
│   ├── rag/               # RAG pipeline (corpus, embedding, index)
│   ├── study/             # Spaced repetition, cards, scheduler
│   ├── graph/             # Concept-question graph
│   ├── eval/               # Evaluation harness
│   └── scripts/           # CLI scripts (build_index, embed_chunks, etc.)
├── frontend/              # Next.js (TypeScript)
└── docs/                  # Documentation
```

## Modules

### `server/`
- **FastAPI app** – REST API for query, study, progress
- **runtime.py** – Process-wide cache (CardStore, GraphRegistry)
- **services/** – query_service, study_service, eval_service
- **config** – Paths (index_root, study_db, graph_registry)

### `legacy/`
- **textbook_search_offline.py** – TF-IDF search (no API keys, offline)
- **PDF pipeline** – page_classifier, section_scanner, section_text_extractor, qa_handler
- **query.py** – Legacy Q&A integration

### `extractors/`
- **pdf_backends.py** – PyMuPDF-based PDF extraction

### `rag/`
- **build_content_corpus.py** – Sections → chunks (normalized)
- **build_index.py** – Chunks → FAISS/BM25 index (optional path)
- **embedding_client.py** – Embedding provider abstraction
- **retrieve.py** – Vector retrieval

### `study/`
- **storage.py** – CardStore (JSONL)
- **scheduler.py** – SM-2 spaced repetition
- **grader.py** – Answer grading
- **plan.py** – Study plan (review, boost, quiz, gap)
- **cli.py** – Study CLI (due, review, quiz, plan)

### `graph/`
- **models.py** – GraphRegistry, QNode, ConceptNode
- **concepts.py** – Concept extraction
- **gaps.py** – Gap scoring for study planning

### `frontend/`
- **Next.js** – Single-page app (Ask, Study, Progress panels)
- **api.ts** – API client (NEXT_PUBLIC_API_BASE)

## Data flow

1. **Indexing**: PDFs → converted/ → chunks_content.jsonl → TextbookSearchOffline (data.json, vectorizer.pkl, vectors.pkl)
2. **Query**: Question → TF-IDF search → compose_answer → GraphRegistry update
3. **Study**: CardStore + GraphRegistry → study plan → due cards → review

## Key entry points

- **API**: `uvicorn server.app:app` (port 8000)
- **Pipeline**: `python run_pipeline.py` or `python -m pdf_processor.main`
- **Study CLI**: `python -m study.cli`
- **Graph CLI**: `python -m graph.cli`
