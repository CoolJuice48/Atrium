const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---- Types ----

export interface BookInfo {
  name: string;
  chunk_count: number;
}

export interface CatalogResponse {
  books: BookInfo[];
  total_chunks: number;
}

export interface QueryResponse {
  question: string;
  answer: string;
  key_points: string[];
  citations: string[];
  confidence: Record<string, unknown>;
  retrieved_chunks: RetrievedChunk[];
}

export interface RetrievedChunk {
  text: string;
  metadata: Record<string, string>;
}

export interface CardSummary {
  card_id: string;
  prompt: string;
  answer: string;
  card_type: string;
  book_name: string;
  due_date: string;
  tags: string[];
}

export interface StudyPlanResponse {
  total_minutes: number;
  review: { cards: CardSummary[]; estimated_minutes: number };
  boost: { cards: CardSummary[]; estimated_minutes: number; sections: unknown[] };
  quiz: Record<string, unknown>;
  gap_boost: { cards: CardSummary[]; estimated_minutes: number; concepts: unknown[] };
  mastery_snapshot: Record<string, unknown>;
  gap_snapshot: unknown[];
}

export interface DueCardsResponse {
  due_count: number;
  cards: CardSummary[];
}

export interface ReviewResponse {
  score: number;
  feedback: string;
  new_schedule: Record<string, unknown>;
}

export interface CardsFromLastAnswerResponse {
  cards_generated: number;
  cards: CardSummary[];
}

export interface ProgressResponse {
  overall_mastery: number;
  by_book: Record<string, number>;
  weakest_sections: unknown[];
  strongest_sections: unknown[];
  total_cards: number;
  due_count: number;
}

// ---- API functions ----

export function getHealth(): Promise<{ status: string }> {
  return request("/health");
}

export function getCatalog(): Promise<CatalogResponse> {
  return request("/catalog");
}

export function postQuery(params: {
  question: string;
  book?: string;
  top_k?: number;
  save_last_answer?: boolean;
}): Promise<QueryResponse> {
  return post("/query", params);
}

export function postPlan(params: {
  minutes?: number;
  book?: string;
}): Promise<StudyPlanResponse> {
  return post("/study/plan", params);
}

export function getDue(): Promise<DueCardsResponse> {
  return request("/study/due");
}

export function postReview(params: {
  card_id: string;
  user_answer: string;
}): Promise<ReviewResponse> {
  return post("/study/review", params);
}

export function postCardsFromLastAnswer(params: {
  max_cards?: number;
}): Promise<CardsFromLastAnswerResponse> {
  return post("/cards/from_last_answer", params);
}

export function getProgress(): Promise<ProgressResponse> {
  return request("/progress");
}
