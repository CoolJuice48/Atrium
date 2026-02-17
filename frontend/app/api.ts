const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const DEFAULT_FETCH_OPTIONS: RequestInit = {
  credentials: "include",
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...DEFAULT_FETCH_OPTIONS,
    ...options,
    headers: { ...(options?.headers as Record<string, string>) },
  });
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
    ...DEFAULT_FETCH_OPTIONS,
  });
}

// ---- Auth ----

export interface UserResponse {
  id: string;
  email: string;
}

export function postRegister(params: {
  email: string;
  password: string;
}): Promise<UserResponse> {
  return post("/auth/register", params);
}

export function postLogin(params: {
  email: string;
  password: string;
}): Promise<UserResponse> {
  return post("/auth/login", params);
}

export function postLogout(): Promise<{ ok: boolean }> {
  return post("/auth/logout", {});
}

export function getAuthMe(): Promise<UserResponse> {
  return request("/auth/me");
}

/** Returns current user or null if not logged in (401). */
export async function getAuthMeOptional(): Promise<UserResponse | null> {
  try {
    return await getAuthMe();
  } catch (e) {
    if (e instanceof Error && e.message.startsWith("401")) return null;
    throw e;
  }
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

export function getHealth(): Promise<{ ok: boolean }> {
  return request("/health");
}

export interface StatusResponse {
  ok: boolean;
  index_root: string;
  pdf_dir: string;
  index_exists: boolean;
  index_ready: boolean;
  chunk_count: number;
  book_counts: { book: string; chunks: number }[];
  consistency?: { ok: boolean; issues: string[] };
}

export function getStatus(): Promise<StatusResponse> {
  return request("/status");
}

export interface BuildReport {
  elapsed_ms: number;
  ingested: { book_id: string; filename: string; title: string; chunk_count: number; ingest_ms: number; status: string }[];
  skipped: { filename: string; reason: string }[];
  failed: { filename: string; error: string }[];
  rebuilt_search_index: boolean;
  avg_ingest_ms: number;
}

export interface IndexBuildResponse {
  ok: boolean;
  index_root: string;
  built: boolean;
  report: BuildReport;
  stats: { chunk_count: number; book_counts: { book: string; chunks: number }[]; consistency?: { ok: boolean; issues: string[] } };
  timings?: { elapsed_ms: number; avg_ingest_ms: number };
}

export function buildIndex(params?: {
  pdf_dir?: string;
  index_root?: string;
}): Promise<IndexBuildResponse> {
  return post("/index/build", params ?? {});
}

export interface RepairReport {
  elapsed_ms: number;
  scanned_books: number;
  repaired_books: { book_id: string; actions: string[] }[];
  error_books: { book_id: string; issues: string[] }[];
  pruned_tmp_count: number;
  rebuilt_library_json: boolean;
  rebuilt_search_index: boolean;
  repairs_changed_state: boolean;
  consistency: { ok: boolean; issues: string[] };
}

export interface IndexRepairResponse {
  ok: boolean;
  index_root: string;
  report: RepairReport;
  stats: { chunk_count: number; book_counts: { book: string; chunks: number }[]; consistency?: { ok: boolean; issues: string[] } };
}

export function repairIndex(params?: {
  index_root?: string;
  mode?: "verify" | "repair";
  rebuild_search_index?: boolean;
  prune_tmp?: boolean;
}): Promise<IndexRepairResponse> {
  return post("/index/repair", params ?? {});
}

// ---- Study Artifacts (per-book) ----

export interface BookWithStudy {
  book_id: string;
  title: string;
  chunk_count: number;
  study: { card_count: number; due_count: number; last_generated_at: string | null; avg_grade: number | null };
}

export function getBooks(): Promise<{ books: BookWithStudy[] }> {
  return request("/books");
}

export function generateStudyCards(bookId: string, params?: { max_cards?: number; strategy?: "simple" | "coverage" }): Promise<{ generated_count: number; skipped_count: number; elapsed_ms: number }> {
  return post(`/books/${bookId}/study/generate`, params ?? {});
}

export interface StudyDueCard {
  card_id: string;
  question: string;
  answer: string;
  source: { page?: number; section?: string };
}

export function getStudyDue(bookId: string, limit?: number): Promise<{ cards: StudyDueCard[] }> {
  const q = limit != null ? `?limit=${limit}` : "";
  return request(`/books/${bookId}/study/due${q}`);
}

export function postStudyReview(bookId: string, cardId: string, grade: number): Promise<{ ease: number; interval_days: number; due_at: string; last_reviewed_at?: string }> {
  return post(`/books/${bookId}/study/review`, { card_id: cardId, grade });
}

export interface ExamQuestion {
  card_id: string;
  prompt: string;
  answer: string;
  card_type: string;
  book_name: string;
  tags: string[];
  citations: { chunk_id: string; chapter: string; section: string; pages: string }[];
}

export interface ExamGenerateResponse {
  ok: boolean;
  book_id: string;
  title: string;
  exam: { questions: ExamQuestion[] };
  meta: { total: number; counts_by_type: Record<string, number>; sampling_occurred?: boolean };
}

export function postExamGenerate(bookId: string, params?: { exam_size?: number; blueprint?: Record<string, number>; seed?: number }): Promise<ExamGenerateResponse> {
  return post(`/books/${bookId}/study/exam/generate`, params ?? {});
}

// ---- Outline & Scoped Summary ----

export interface OutlineItem {
  id: string;
  title: string;
  level: number;
  start_page: number;
  end_page: number;
  parent_id: string | null;
}

export interface OutlineResponse {
  outline_id: string;
  items: OutlineItem[];
}

export interface ScopedSummaryResponse {
  summary_markdown: string;
  bullets: string[];
  citations: string[];
  key_terms: string[];
}

export function getBookOutline(bookId: string): Promise<OutlineResponse> {
  return request(`/books/${bookId}/outline`);
}

export function postScopedSummary(
  bookId: string,
  params: { outline_id: string; scope: { item_ids: string[] }; options?: { bullets_target?: number; max_pages?: number } }
): Promise<ScopedSummaryResponse> {
  return post(`/books/${bookId}/summaries`, params);
}

export interface PracticeExamQuestion {
  q_type: string;
  prompt: string;
  answer: string;
  citations: { chunk_id: string; pages: string }[];
}

export interface PracticeExamResponse {
  exam_id: string;
  scope_label: string;
  resolved_ranges: { start: number; end: number }[];
  questions: PracticeExamQuestion[];
  citations: { chunk_id: string; pages: string }[];
}

export function postScopedPracticeExam(
  bookId: string,
  params: {
    outline_id: string;
    scope: { item_ids: string[] };
    options?: { total_questions?: number; max_pages?: number };
  }
): Promise<PracticeExamResponse> {
  return post(`/books/${bookId}/practice-exams`, params);
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

// ---- Syllabus (zero-knowledge) ----

export interface SyllabusUploadResponse {
  syllabus_id: string;
}

export function postSyllabusUpload(formData: FormData): Promise<SyllabusUploadResponse> {
  return fetch(`${API_BASE}/syllabus/upload`, {
    method: "POST",
    body: formData,
    credentials: "include",
  }).then(async (res) => {
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json();
  });
}

export interface PlanGenerateResponse {
  plan_id: string;
  summary: Record<string, unknown>;
  plan_json?: Record<string, unknown>;
}

export function postPlanGenerateFromFeatures(params: {
  syllabus_id: string;
  path_id: string;
  features: { topics?: string[]; weeks?: number[]; textbooks?: string[] };
}): Promise<PlanGenerateResponse> {
  return post("/plan/generate_from_features", params);
}

// ---- Packs (backend serves catalog.json from hosted dist) ----

export interface PackCatalogEntry {
  pack_id: string;
  version: string;
  title: string;
  description?: string;
  module?: { id: string; title: string; order: number; prereqs?: string[] };
  prereqs?: string[];
  size_bytes?: number;
  sha256?: string;
  download_url?: string;
  book_count?: number;
  licenses_summary?: string[];
}

/** Start pack install. Returns job_id. */
export function postPackInstall(params: {
  pack_id: string;
  pack_title: string;
  download_url: string;
}): Promise<{ job_id: string }> {
  return post("/packs/install", params);
}

/** Get install job status. */
export function getPackInstallStatus(jobId: string): Promise<PackInstallStatus> {
  return request(`/packs/install/${jobId}`);
}

export interface PackInstallStatus {
  job_id: string;
  pack_id: string;
  pack_title: string;
  status: string;
  phase: string;
  message: string;
  current: number;
  total: number;
  error?: string;
  result?: { ingested: unknown[]; skipped: unknown[]; failed: unknown[] };
}

/** Cancel install job. */
export function postPackInstallCancel(jobId: string): Promise<{ ok: boolean }> {
  return post(`/packs/install/${jobId}/cancel`, {});
}

// ---- User PDF upload ----

export function postUploadPdf(formData: FormData): Promise<{ job_id: string }> {
  return fetch(`${API_BASE}/uploads/pdf`, {
    method: "POST",
    body: formData,
    credentials: "include",
  }).then(async (res) => {
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json();
  });
}

export interface UploadJobStatus {
  job_id: string;
  filename: string;
  status: string;
  phase: string;
  message: string;
  progress: { current: number; total: number };
  error?: string;
  result?: { book_id: string; display_title: string; chunk_count: number };
}

export function getUploadStatus(jobId: string): Promise<UploadJobStatus> {
  return request(`/uploads/${jobId}`);
}

export function postUploadCancel(jobId: string): Promise<{ ok: boolean }> {
  return post(`/uploads/${jobId}/cancel`, {});
}

export function patchBookMetadata(
  bookId: string,
  params: { display_title?: string; subject_tags?: string[]; course_tags?: string[] }
): Promise<{ ok: boolean }> {
  return fetch(`${API_BASE}/books/${bookId}/metadata`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    credentials: "include",
  }).then(async (res) => {
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json();
  });
}

/** Fetch pack catalog from backend GET /packs/catalog. */
export async function getPacksCatalog(): Promise<PackCatalogEntry[]> {
  try {
    const data = await request<PackCatalogEntry[] | { packs?: PackCatalogEntry[] }>("/packs/catalog");
    if (Array.isArray(data)) return data;
    return (data as { packs?: PackCatalogEntry[] }).packs ?? [];
  } catch {
    return [];
  }
}

// ---- Packs (legacy: external CDN) ----

const PACKS_BASE = process.env.NEXT_PUBLIC_PACKS_BASE ?? "";

export function fetchPackCatalog(packsBase?: string): Promise<PackCatalogEntry[]> {
  const base = packsBase ?? PACKS_BASE;
  if (!base) return Promise.resolve([]);
  return fetch(`${base.replace(/\/$/, "")}/catalog.json`, {
    credentials: "include",
  }).then((r) => (r.ok ? r.json() : []));
}

export function downloadPack(
  packsBase: string,
  packDownloadUrl: string
): Promise<Blob> {
  const base = packsBase.replace(/\/$/, "");
  const url = packDownloadUrl.startsWith("http") ? packDownloadUrl : `${base}/${packDownloadUrl}`;
  return fetch(url).then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`Failed to download: ${url}`))));
}
