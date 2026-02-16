# Atrium Frontend

Minimal Next.js (TypeScript) frontend for the Atrium learning platform. One page with three panels: **Ask**, **Study**, and **Progress**.

## Prerequisites

- Node.js 18+
- Atrium FastAPI backend running (see repo root)

## Setup

```bash
cd frontend
npm install
```

## Run

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## API base URL

The frontend calls the FastAPI backend. Set `NEXT_PUBLIC_API_BASE` to override the default:

```bash
# Default: http://localhost:8000
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

Or create `.env.local`:

```
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

## Endpoints used

- `GET /health` – API status
- `GET /catalog` – Book list
- `POST /query` – Ask a question
- `POST /cards/from_last_answer` – Generate cards from last answer
- `POST /study/plan` – Get study plan
- `GET /study/due` – Due cards
- `POST /study/review` – Submit card review
- `GET /progress` – Mastery and stats
