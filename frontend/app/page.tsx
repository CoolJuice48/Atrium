"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { AuthGate } from "./AuthGate";
import { useAuth } from "./AuthContext";
import {
  getHealth,
  getStatus,
  getCatalog,
  buildIndex,
  repairIndex,
  getBooks,
  generateStudyCards,
  getStudyDue,
  postStudyReview,
  postExamGenerate,
  postQuery,
  postCardsFromLastAnswer,
  postPlan,
  getDue,
  postReview,
  getProgress,
  getPacksCatalog,
  postPackInstall,
  postPackInstallCancel,
  postUploadPdf,
  postUploadCancel,
  type CatalogResponse,
  type QueryResponse,
  type StudyPlanResponse,
  type DueCardsResponse,
  type ProgressResponse,
  type CardSummary,
  type StatusResponse,
  type IndexBuildResponse,
  type BuildReport,
  type IndexRepairResponse,
  type RepairReport,
  type BookWithStudy,
  type StudyDueCard,
  type PackCatalogEntry,
  type PackInstallStatus,
  type UploadJobStatus,
  type ExamGenerateResponse,
  type ExamQuestion,
} from "./api";
import { SyllabusUploadPanel } from "./SyllabusUploadPanel";
import { ScopedSummaryPanel } from "./ScopedSummaryPanel";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const EXAMPLE_QUESTIONS = [
  "Give me a 10-bullet summary",
  "What are the key terms and definitions?",
  "Generate a 20-question practice exam",
];

const ADVANCED_STORAGE_KEY = "atrium-advanced-open";
const LAST_BOOK_STORAGE_KEY = "atrium-last-book-id";

function HomeContent() {
  const [apiStatus, setApiStatus] = useState<"ok" | "err" | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [books, setBooks] = useState<BookWithStudy[]>([]);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [packsCatalog, setPacksCatalog] = useState<PackCatalogEntry[]>([]);
  const [uploadInProgress, setUploadInProgress] = useState(false);
  const [uploadJustCompleted, setUploadJustCompleted] = useState<{
    bookId: string;
    displayTitle: string;
  } | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(ADVANCED_STORAGE_KEY) === "true";
  });
  const [selectedBookId, setSelectedBookId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(LAST_BOOK_STORAGE_KEY) ?? "";
  });
  const [triggerExamForBookId, setTriggerExamForBookId] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await getStatus();
      setStatus(s);
      return s;
    } catch {
      setStatus(null);
      return null;
    }
  }, []);

  const refreshBooks = useCallback(async () => {
    try {
      const res = await getBooks();
      setBooks(res.books ?? []);
      return res.books ?? [];
    } catch {
      setBooks([]);
      return [];
    }
  }, []);

  const refreshCatalog = useCallback(async () => {
    try {
      const c = await getCatalog();
      setCatalog(c);
    } catch {
      setCatalog(null);
    }
  }, []);

  const refreshAll = useCallback(() => {
    refreshStatus();
    refreshBooks();
    refreshCatalog();
  }, [refreshStatus, refreshBooks, refreshCatalog]);

  useEffect(() => {
    getHealth()
      .then(() => setApiStatus("ok"))
      .catch(() => setApiStatus("err"));
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    refreshBooks();
  }, [refreshBooks]);

  useEffect(() => {
    getPacksCatalog().then(setPacksCatalog);
  }, []);

  useEffect(() => {
    if (status?.index_ready) {
      refreshCatalog();
    } else {
      setCatalog(null);
    }
  }, [status?.index_ready, refreshCatalog]);

  useEffect(() => {
    if (advancedOpen !== undefined && typeof window !== "undefined") {
      localStorage.setItem(ADVANCED_STORAGE_KEY, String(advancedOpen));
    }
  }, [advancedOpen]);

  useEffect(() => {
    if (selectedBookId && typeof window !== "undefined") {
      localStorage.setItem(LAST_BOOK_STORAGE_KEY, selectedBookId);
    }
  }, [selectedBookId]);

  const hasBooks = books.length > 0;
  const hasReadyBooks = books.some((b) => b.chunk_count > 0);
  const isIndexMissing = !status?.index_exists || !status?.index_ready;

  useEffect(() => {
    if (hasBooks && selectedBookId && !books.some((b) => b.book_id === selectedBookId)) {
      setSelectedBookId(books[0].book_id);
    } else if (hasBooks && !selectedBookId) {
      setSelectedBookId(books[0].book_id);
    }
  }, [hasBooks, books, selectedBookId]);

  const { user, logout } = useAuth();

  const statusChipLabel = !hasBooks
    ? "No documents yet"
    : hasBooks && !hasReadyBooks
      ? "Indexing…"
      : "Ready";

  const statusChipClass = !hasBooks ? "warn" : hasReadyBooks ? "ok" : "warn";

  return (
    <div className="app">
      <header className="header">
        <h1>Atrium</h1>
        {user && (
          <span className="user-chip">
            {user.email}
            <button
              type="button"
              className="secondary"
              onClick={() => logout()}
              style={{ marginLeft: 8, padding: "2px 8px", fontSize: "0.75rem" }}
            >
              Log out
            </button>
          </span>
        )}
        {apiStatus && (
          <span className={`status-chip ${apiStatus}`}>
            {apiStatus === "ok" ? "API connected" : "API offline"}
          </span>
        )}
        {(hasBooks || status) && (
          <span className={`status-chip ${statusChipClass}`}>
            {statusChipLabel}
          </span>
        )}
      </header>

      <main>
        <UploadHeroPanel
          isHero={!hasBooks}
          onUploadStart={() => setUploadInProgress(true)}
          onUploadComplete={(bookId, displayTitle) => {
            setUploadInProgress(false);
            setUploadJustCompleted({ bookId, displayTitle });
            setSelectedBookId(bookId);
            refreshAll();
          }}
          onUploadFail={() => setUploadInProgress(false)}
          onUploadCancel={() => setUploadInProgress(false)}
        />

        {!hasBooks && (
          <div className="section-muted mb" style={{ padding: "16px 20px", marginBottom: 24 }}>
            <h3 style={{ fontSize: "0.9rem", marginBottom: 12 }}>What happens next</h3>
            <ol style={{ margin: 0, paddingLeft: 20, fontSize: "0.9rem", lineHeight: 1.8 }}>
              <li>We index your PDF</li>
              <li>You ask questions</li>
              <li>We generate practice exams &amp; flashcards</li>
            </ol>
          </div>
        )}

        <AdvancedAccordion
          open={advancedOpen}
          onToggle={() => setAdvancedOpen((o) => !o)}
          children={
            <>
              {packsCatalog.length > 0 && (
                <PacksCatalogPanel
                  packs={packsCatalog}
                  onInstalled={refreshAll}
                />
              )}
              <SyllabusUploadPanel />
              {status && !status.index_ready && (
                <BuildIndexPanel
                  defaultPdfDir={status.pdf_dir}
                  defaultIndexRoot={status.index_root}
                  onBuilt={refreshAll}
                />
              )}
              {status?.index_exists && (
                <RepairPanel
                  indexRoot={status.index_root}
                  consistencyOk={status.consistency?.ok ?? true}
                  onRepaired={refreshAll}
                />
              )}
            </>
          }
        />

        {hasBooks && (
          <>
            <AskPanel
              catalog={catalog}
              books={books}
              indexReady={status?.index_ready}
              uploadInProgress={uploadInProgress}
              uploadJustCompleted={uploadJustCompleted}
              selectedBookId={selectedBookId}
              onSelectBook={setSelectedBookId}
              onClearUploadCompleted={() => setUploadJustCompleted(null)}
              onQuickExamRequest={() => selectedBookId && setTriggerExamForBookId(selectedBookId)}
            />
            <ExamPanel
              selectedBookId={selectedBookId}
              onSelectBook={setSelectedBookId}
              books={books}
              triggerGenerate={triggerExamForBookId}
              onTriggerConsumed={() => setTriggerExamForBookId(null)}
            />
            {selectedBookId && (
              <ScopedSummaryPanel
                bookId={selectedBookId}
                bookTitle={books.find((b) => b.book_id === selectedBookId)?.title ?? "Book"}
              />
            )}
            <StudyArtifactsPanel
              selectedBookId={selectedBookId}
              onSelectBook={setSelectedBookId}
              books={books}
              onUpdated={refreshAll}
            />
            <StudyPanel catalog={catalog} />
            <ProgressPanel />
          </>
        )}
      </main>
    </div>
  );
}

export default function Home() {
  return (
    <AuthGate>
      <HomeContent />
    </AuthGate>
  );
}

function AdvancedAccordion({
  open,
  onToggle,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="advanced-accordion panel">
      <button
        type="button"
        className="advanced-accordion-trigger"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span>Advanced</span>
        <span className="advanced-accordion-caret" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && <div className="advanced-accordion-content">{children}</div>}
    </div>
  );
}

function UploadHeroPanel({
  isHero = true,
  onUploadStart,
  onUploadComplete,
  onUploadFail,
  onUploadCancel,
}: {
  isHero?: boolean;
  onUploadStart: () => void;
  onUploadComplete: (bookId: string, displayTitle: string) => void;
  onUploadFail: () => void;
  onUploadCancel: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [displayTitle, setDisplayTitle] = useState("");
  const [subjectTags, setSubjectTags] = useState("");
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<UploadJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = (f: File | null) => {
    setFile(f);
    if (f && !displayTitle) setDisplayTitle(f.name.replace(/\.pdf$/i, ""));
    setError(null);
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    setStatus(null);
    onUploadStart();
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (displayTitle) formData.append("display_title", displayTitle);
      const { job_id } = await postUploadPdf(formData);

      const es = new EventSource(`${API_BASE}/uploads/${job_id}/stream`, {
        withCredentials: true,
      });
      es.onmessage = (e) => {
        const data = JSON.parse(e.data);
        setStatus(data as UploadJobStatus);
        if (data.status === "completed" && data.result) {
          es.close();
          setUploading(false);
          setFile(null);
          setStatus(null);
          setDisplayTitle("");
          onUploadComplete(data.result.book_id, data.result.display_title);
        } else if (data.status === "failed" || data.status === "cancelled") {
          es.close();
          setUploading(false);
          if (data.status === "failed") onUploadFail();
          else onUploadCancel();
        }
      };
      es.onerror = () => {
        es.close();
        setUploading(false);
      };
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setUploading(false);
      onUploadFail();
    }
  };

  const cancel = () => {
    if (status?.job_id) postUploadCancel(status.job_id);
    onUploadCancel();
  };

  return (
    <section className={`panel upload-hero-panel ${isHero ? "hero-panel" : ""}`}>
      <h2>Upload & Study</h2>
      <p className="mb" style={{ fontSize: "0.9rem" }}>
        {isHero
          ? "Upload a lecture PDF, study guide, or textbook chapter."
          : "Upload another PDF to add to your library."}
      </p>
      {isHero && (
        <p className="section-muted mb" style={{ fontSize: "0.85rem" }}>
          Text-based PDFs work best. Scans may not extract text yet.
        </p>
      )}
      <div
        className={`upload-dropzone ${dragOver ? "drag-over" : ""} ${isHero ? "upload-dropzone-hero" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files[0];
          if (f?.name.toLowerCase().endsWith(".pdf")) handleFile(f);
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          style={{ display: "none" }}
        />
        {file ? (
          <span>{file.name}</span>
        ) : (
          <span>Drop PDF here or click to choose</span>
        )}
      </div>
      {file && (
        <div className="row mb" style={{ marginTop: 8 }}>
          <label>
            Title
            <input
              type="text"
              value={displayTitle}
              onChange={(e) => setDisplayTitle(e.target.value)}
              placeholder="Document title"
              disabled={uploading}
              style={{ display: "block", width: "100%", maxWidth: 280, marginTop: 4 }}
            />
          </label>
        </div>
      )}
      {error && <p className="error mb">{error}</p>}
      {status && (status.status === "running" || status.status === "queued") && (
        <div className="upload-progress mb">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: status.progress?.total
                  ? `${(100 * (status.progress.current || 0)) / status.progress.total}%`
                  : "30%",
              }}
            />
          </div>
          <p style={{ fontSize: "0.9rem", marginTop: 4 }}>
            {status.message}
            {status.progress?.total > 0 && (
              <span style={{ color: "var(--text-secondary)" }}>
                {" "}({status.progress.current}/{status.progress.total})
              </span>
            )}
          </p>
          <button className="secondary" onClick={cancel} style={{ marginTop: 8 }}>
            Cancel
          </button>
        </div>
      )}
      {status?.status === "failed" && (
        <p className="error mb">
          {status.error}
          <button className="secondary" style={{ marginLeft: 8 }} onClick={() => { setStatus(null); setFile(null); }}>
            Try again
          </button>
        </p>
      )}
      {file && !uploading && status?.status !== "completed" && status?.status !== "failed" && (
        <button className="primary" onClick={handleUpload}>
          Upload & index
        </button>
      )}
    </section>
  );
}

function PacksCatalogPanel({
  packs,
  onInstalled,
}: {
  packs: PackCatalogEntry[];
  onInstalled?: () => void;
}) {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

  return (
    <section className="panel">
      <h2>Content packs</h2>
      <p className="mb" style={{ fontSize: "0.9rem" }}>
        Install packs to add books to your library.
      </p>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {packs.map((p) => (
          <PackCatalogItem
            key={p.pack_id}
            pack={p}
            apiBase={API_BASE}
            onInstalled={onInstalled}
          />
        ))}
      </ul>
    </section>
  );
}

function PackCatalogItem({
  pack,
  apiBase,
  onInstalled,
}: {
  pack: PackCatalogEntry;
  apiBase: string;
  onInstalled?: () => void;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<PackInstallStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const install = async () => {
    setError(null);
    setStatus(null);
    try {
      const downloadUrl = pack.download_url ?? `packs/${pack.pack_id}-${pack.version}.zip`;
      const { job_id } = await postPackInstall({
        pack_id: pack.pack_id,
        pack_title: pack.title ?? pack.pack_id,
        download_url: downloadUrl,
      });
      setJobId(job_id);

      const es = new EventSource(`${apiBase}/packs/install/${job_id}/stream`, {
        withCredentials: true,
      });
      es.onmessage = (e) => {
        const data = JSON.parse(e.data);
        setStatus(data as PackInstallStatus);
        if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") {
          es.close();
          if (data.status === "completed") onInstalled?.();
        }
      };
      es.onerror = () => {
        es.close();
      };
    } catch (e) {
      setError(e instanceof Error ? e.message : "Install failed");
    }
  };

  const cancel = async () => {
    if (!jobId) return;
    try {
      await postPackInstallCancel(jobId);
    } catch {
      // ignore
    }
  };

  const isActive = status && !["completed", "failed", "cancelled"].includes(status.status);

  return (
    <li
      style={{
        padding: "12px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <strong>{pack.title}</strong>
          {pack.version && (
            <span style={{ marginLeft: 8, fontSize: "0.85rem", color: "var(--text-secondary)" }}>
              v{pack.version}
            </span>
          )}
          {pack.description && (
            <p style={{ margin: "4px 0 0", fontSize: "0.9rem", color: "var(--text-secondary)" }}>
              {pack.description}
            </p>
          )}
        </div>
        <div style={{ flexShrink: 0 }}>
          {!jobId ? (
            <button className="primary" onClick={install} disabled={!!jobId}>
              Install
            </button>
          ) : isActive ? (
            <button className="secondary" onClick={cancel}>
              Cancel
            </button>
          ) : null}
        </div>
      </div>
      {error && <p className="error" style={{ marginTop: 8 }}>{error}</p>}
      {status && (
        <div
          className="pack-install-progress"
          style={{
            marginTop: 8,
            fontSize: "0.9rem",
            padding: 8,
            background: "var(--bg)",
            borderRadius: 4,
          }}
        >
          {status.status === "completed" && (
            <span className="success">{status.message}</span>
          )}
          {status.status === "failed" && (
            <span className="error">{status.error ?? status.message}</span>
          )}
          {status.status === "cancelled" && (
            <span style={{ color: "var(--text-secondary)" }}>Cancelled</span>
          )}
          {isActive && (
            <>
              <span>{status.message}</span>
              {status.total > 0 && (
                <span style={{ marginLeft: 8, color: "var(--text-secondary)" }}>
                  {status.current}/{status.total}
                </span>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

function BuildIndexPanel({
  defaultPdfDir,
  defaultIndexRoot,
  onBuilt,
}: {
  defaultPdfDir: string;
  defaultIndexRoot: string;
  onBuilt: () => void;
}) {
  const [pdfDir, setPdfDir] = useState(defaultPdfDir);
  const [indexRoot, setIndexRoot] = useState(defaultIndexRoot);
  const [building, setBuilding] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [lastReport, setLastReport] = useState<BuildReport | null>(null);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!building) return;
    const start = Date.now();
    const id = setInterval(() => setElapsedMs(Date.now() - start), 200);
    return () => clearInterval(id);
  }, [building]);

  const handleBuild = async () => {
    setBuilding(true);
    setMessage(null);
    setElapsedMs(0);
    try {
      const res: IndexBuildResponse = await buildIndex({ pdf_dir: pdfDir, index_root: indexRoot });
      setLastReport(res.report);
      setMessage({ type: "ok", text: "Index built successfully." });
      onBuilt();
    } catch (e) {
      const text = e instanceof Error ? e.message : "Build failed";
      setMessage({ type: "err", text });
    } finally {
      setBuilding(false);
      setElapsedMs(0);
    }
  };

  return (
    <section className="panel build-index-panel">
      <h2>Build Index</h2>
      <p className="mb">No index yet. Add PDFs to the PDF directory, then build.</p>
      <div className="row mb">
        <label>
          PDF dir:{" "}
          <input
            type="text"
            value={pdfDir}
            onChange={(e) => setPdfDir(e.target.value)}
            disabled={building}
            style={{ width: 200 }}
          />
        </label>
      </div>
      <div className="row mb">
        <label>
          Index root:{" "}
          <input
            type="text"
            value={indexRoot}
            onChange={(e) => setIndexRoot(e.target.value)}
            disabled={building}
            style={{ width: 200 }}
          />
        </label>
      </div>
      <div className="row mb">
        <button
          className="primary"
          onClick={handleBuild}
          disabled={building}
        >
          {building ? "Building…" : "Build Index"}
        </button>
        {building && <span className="build-timer" style={{ marginLeft: 12 }}>{Math.round(elapsedMs / 1000)}s</span>}
      </div>
      {message && (
        <p className={message.type === "ok" ? "success" : "error"}>{message.text}</p>
      )}
      {lastReport && (
        <BuildResultsPanel report={lastReport} />
      )}
    </section>
  );
}

function BuildResultsPanel({ report }: { report: BuildReport }) {
  const { ingested, skipped, failed, rebuilt_search_index, elapsed_ms, avg_ingest_ms } = report;
  const readyCount = ingested.filter((i) => i.status === "ready").length;

  return (
    <div className="build-results mt">
      <h3 style={{ fontSize: "0.9rem", marginBottom: 8 }}>Build summary</h3>
      <ul className="build-summary-list">
        <li>Elapsed: {elapsed_ms}ms</li>
        <li>Search index rebuilt: {rebuilt_search_index ? "Yes" : "No"}</li>
        {readyCount > 0 && <li>Avg ingest: {Math.round(avg_ingest_ms)}ms</li>}
      </ul>
      {ingested.length > 0 && (
        <div className="build-list">
          <strong>Ingested ({ingested.length}):</strong>
          <ul>
            {ingested.map((i) => (
              <li key={i.book_id}>
                {i.filename} → {i.title} ({i.chunk_count} chunks, {i.status})
              </li>
            ))}
          </ul>
        </div>
      )}
      {skipped.length > 0 && (
        <div className="build-list">
          <strong>Skipped ({skipped.length}):</strong>
          <ul>
            {skipped.map((s, idx) => (
              <li key={idx}>{s.filename} — {s.reason}</li>
            ))}
          </ul>
        </div>
      )}
      {failed.length > 0 && (
        <div className="build-list">
          <strong>Failed ({failed.length}):</strong>
          <ul>
            {failed.map((f, idx) => (
              <li key={idx}>{f.filename}: {f.error}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RepairPanel({
  indexRoot,
  consistencyOk,
  onRepaired,
}: {
  indexRoot: string;
  consistencyOk: boolean;
  onRepaired: () => void;
}) {
  const [repairing, setRepairing] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [lastReport, setLastReport] = useState<RepairReport | null>(null);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!repairing) return;
    const start = Date.now();
    const id = setInterval(() => setElapsedMs(Date.now() - start), 200);
    return () => clearInterval(id);
  }, [repairing]);

  const handleRepair = async () => {
    setRepairing(true);
    setMessage(null);
    setElapsedMs(0);
    try {
      const res: IndexRepairResponse = await repairIndex({
        index_root: indexRoot,
        mode: "repair",
        prune_tmp: true,
      });
      setLastReport(res.report);
      setMessage({ type: "ok", text: "Repair completed." });
      onRepaired();
    } catch (e) {
      const text = e instanceof Error ? e.message : "Repair failed";
      setMessage({ type: "err", text });
    } finally {
      setRepairing(false);
      setElapsedMs(0);
    }
  };

  const handleVerify = async () => {
    setRepairing(true);
    setMessage(null);
    setElapsedMs(0);
    try {
      const res: IndexRepairResponse = await repairIndex({
        index_root: indexRoot,
        mode: "verify",
      });
      setLastReport(res.report);
      setMessage({ type: "ok", text: "Verify completed." });
    } catch (e) {
      const text = e instanceof Error ? e.message : "Verify failed";
      setMessage({ type: "err", text });
    } finally {
      setRepairing(false);
      setElapsedMs(0);
    }
  };

  return (
    <section className={`panel repair-panel ${!consistencyOk ? "repair-panel-warn" : ""}`}>
      <h2>Verify & Repair</h2>
      {!consistencyOk && (
        <p className="mb" style={{ color: "var(--warning, #ca8a04)" }}>
          Index has consistency issues. Run repair to fix metadata and prune temp files.
        </p>
      )}
      <p className="mb" style={{ fontSize: "0.9rem" }}>
        Rebuild library metadata from disk, clean temp files, and optionally rebuild search index.
      </p>
      <div className="row mb">
        <button
          className="primary"
          onClick={handleRepair}
          disabled={repairing}
        >
          {repairing ? "Repairing…" : "Repair"}
        </button>
        <button
          className="secondary"
          onClick={handleVerify}
          disabled={repairing}
          style={{ marginLeft: 8 }}
        >
          Verify only
        </button>
        {repairing && <span className="build-timer" style={{ marginLeft: 12 }}>{Math.round(elapsedMs / 1000)}s</span>}
      </div>
      {message && (
        <p className={message.type === "ok" ? "success" : "error"}>{message.text}</p>
      )}
      {lastReport && (
        <RepairResultsPanel report={lastReport} />
      )}
    </section>
  );
}

function RepairResultsPanel({ report }: { report: RepairReport }) {
  const { repaired_books, error_books, pruned_tmp_count, rebuilt_library_json, rebuilt_search_index, elapsed_ms, consistency } = report;

  return (
    <div className="build-results mt">
      <h3 style={{ fontSize: "0.9rem", marginBottom: 8 }}>Repair summary</h3>
      <ul className="build-summary-list">
        <li>Elapsed: {elapsed_ms}ms</li>
        <li>Library rebuilt: {rebuilt_library_json ? "Yes" : "No"}</li>
        <li>Search index rebuilt: {rebuilt_search_index ? "Yes" : "No"}</li>
        {pruned_tmp_count > 0 && <li>Pruned {pruned_tmp_count} temp file(s)</li>}
        <li>Consistency: {consistency.ok ? "OK" : "Issues"}</li>
      </ul>
      {repaired_books.length > 0 && (
        <div className="build-list">
          <strong>Repaired ({repaired_books.length}):</strong>
          <ul>
            {repaired_books.map((r) => (
              <li key={r.book_id}>{r.book_id}: {r.actions.join(", ")}</li>
            ))}
          </ul>
        </div>
      )}
      {error_books.length > 0 && (
        <div className="build-list">
          <strong>Errors ({error_books.length}):</strong>
          <ul>
            {error_books.map((e) => (
              <li key={e.book_id}>{e.book_id}: {e.issues.join("; ")}</li>
            ))}
          </ul>
        </div>
      )}
      {!consistency.ok && consistency.issues.length > 0 && (
        <div className="build-list">
          <strong>Consistency issues:</strong>
          <ul>
            {consistency.issues.map((i, idx) => (
              <li key={idx}>{i}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function AskPanel({
  catalog,
  books,
  indexReady,
  uploadInProgress,
  uploadJustCompleted,
  selectedBookId,
  onSelectBook,
  onClearUploadCompleted,
  onQuickExamRequest,
}: {
  catalog: CatalogResponse | null;
  books: BookWithStudy[];
  indexReady?: boolean;
  uploadInProgress?: boolean;
  uploadJustCompleted?: { bookId: string; displayTitle: string } | null;
  selectedBookId: string;
  onSelectBook: (id: string) => void;
  onClearUploadCompleted?: () => void;
  onQuickExamRequest?: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [book, setBook] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [cardsCreated, setCardsCreated] = useState<number | null>(null);
  const askInputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (uploadJustCompleted) {
      onSelectBook(uploadJustCompleted.bookId);
      const match = catalog?.books?.find(
        (b) => b.name === uploadJustCompleted!.displayTitle || b.name.replace(/\.pdf$/i, "") === uploadJustCompleted!.displayTitle
      );
      if (match) setBook(match.name);
      else if (books.find((b) => b.book_id === uploadJustCompleted!.bookId)) {
        setBook(books.find((b) => b.book_id === uploadJustCompleted!.bookId)!.title);
      }
      askInputRef.current?.focus();
    }
  }, [uploadJustCompleted, catalog?.books, books, onSelectBook]);

  useEffect(() => {
    if (selectedBookId && !uploadJustCompleted) {
      const b = books.find((x) => x.book_id === selectedBookId);
      const match = catalog?.books?.find((c) => c.name === b?.title || c.name.replace(/\.pdf$/i, "") === b?.title?.replace(/\.pdf$/i, ""));
      if (match) setBook(match.name);
      else if (b) setBook(b.title);
    }
  }, [selectedBookId, books, catalog?.books]);

  const handleQuery = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await postQuery({
        question: question.trim(),
        book: book || undefined,
        save_last_answer: true,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCards = async () => {
    if (!result) return;
    setLoading(true);
    setError(null);
    try {
      const res = await postCardsFromLastAnswer({ max_cards: 6 });
      setCardsCreated(res.cards_generated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const hasBooks = catalog?.books && catalog.books.length > 0;
  const showExampleQuestions = uploadJustCompleted || selectedBookId;

  if (uploadInProgress) {
    return (
      <section className="panel">
        <h2>Ask</h2>
        <p className="loading">Indexing… Your document will be ready in a moment.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>Ask</h2>
      {uploadJustCompleted && (
        <p className="success mb" style={{ fontSize: "0.9rem" }}>
          Ready! Try a question about {uploadJustCompleted.displayTitle}.
          {onClearUploadCompleted && (
            <button className="secondary" style={{ marginLeft: 8 }} onClick={onClearUploadCompleted}>
              Dismiss
            </button>
          )}
        </p>
      )}
      {showExampleQuestions && (
        <div className="example-questions mb">
          <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: 4 }}>Try example questions:</p>
          {EXAMPLE_QUESTIONS.map((q, i) => (
            <button
              key={i}
              className="secondary"
              style={{ display: "block", marginBottom: 4, textAlign: "left", width: "100%" }}
              onClick={() => {
                if (i === 2 && onQuickExamRequest) onQuickExamRequest();
                else setQuestion(q);
              }}
            >
              {q}
            </button>
          ))}
        </div>
      )}
      <div className="row mb">
        <textarea
          ref={askInputRef}
          placeholder="Ask a question about your textbooks..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={2}
          disabled={loading}
        />
      </div>
      <div className="row mb">
        <select
          value={book}
          onChange={(e) => {
            const v = e.target.value;
            setBook(v);
            const b = books.find((x) => x.title === v || x.title.replace(/\.pdf$/i, "") === v);
            if (b) onSelectBook(b.book_id);
            else if (catalog?.books?.find((x) => x.name === v)) {
              const cb = catalog.books.find((x) => x.name === v);
              const mb = books.find((x) => x.title === cb?.name || x.title.replace(/\.pdf$/i, "") === cb?.name?.replace(/\.pdf$/i, ""));
              if (mb) onSelectBook(mb.book_id);
            }
          }}
          disabled={loading}
          style={{ maxWidth: 200 }}
        >
          <option value="">All books</option>
          {(catalog?.books?.length ? catalog.books : books).map((b) => {
            const name = "name" in b ? (b as { name: string }).name : (b as BookWithStudy).title;
            return (
              <option key={name} value={name}>
                {name}
              </option>
            );
          })}
        </select>
        <button
          className="primary"
          onClick={handleQuery}
          disabled={loading || !question.trim()}
        >
          {loading ? "Searching…" : "Ask"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="answer-block mt">
          <p className="answer-text">{result.answer}</p>
          {result.key_points.length > 0 && (
            <ul>
              {result.key_points.map((kp, i) => (
                <li key={i}>{kp}</li>
              ))}
            </ul>
          )}
          {result.citations.length > 0 && (
            <div className="sources">
              <h3>Sources</h3>
              {result.citations.map((c, i) => (
                <div key={i} className="source-item">
                  {c}
                </div>
              ))}
            </div>
          )}
          <div className="mt">
            <button
              className="primary"
              onClick={handleCreateCards}
              disabled={loading}
            >
              Generate study cards from this document
            </button>
            {cardsCreated !== null && (
              <span className="created-count" style={{ marginLeft: 8 }}>
                {cardsCreated > 0
                  ? `Created ${cardsCreated} card(s)`
                  : "No new cards generated"}
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function StudyArtifactsPanel({
  selectedBookId,
  onSelectBook,
  books: booksProp,
  onUpdated,
}: {
  selectedBookId: string;
  onSelectBook: (id: string) => void;
  books: BookWithStudy[];
  onUpdated: () => void;
}) {
  const [loadingBooks, setLoadingBooks] = useState(false);
  const books = booksProp.length > 0 ? booksProp : [] as BookWithStudy[];
  const [localBooks, setLocalBooks] = useState<BookWithStudy[]>([]);
  const booksToUse = books.length > 0 ? books : localBooks;
  const [generating, setGenerating] = useState(false);
  const [dueCards, setDueCards] = useState<StudyDueCard[]>([]);
  const [loadingDue, setLoadingDue] = useState(false);
  const [reviewingCard, setReviewingCard] = useState<StudyDueCard | null>(null);
  const [showAnswer, setShowAnswer] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadBooks = useCallback(async () => {
    setLoadingBooks(true);
    setError(null);
    try {
      const res = await getBooks();
      setLocalBooks(res.books ?? []);
      if (!selectedBookId && res.books?.[0]) onSelectBook(res.books[0].book_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load books");
    } finally {
      setLoadingBooks(false);
    }
  }, [onSelectBook, selectedBookId]);

  useEffect(() => {
    if (booksProp.length === 0) loadBooks();
  }, [booksProp.length, loadBooks]);

  useEffect(() => {
    if (selectedBookId) {
      setLoadingDue(true);
      getStudyDue(selectedBookId, 20)
        .then((res) => setDueCards(res.cards))
        .catch(() => setDueCards([]))
        .finally(() => setLoadingDue(false));
    } else {
      setDueCards([]);
    }
  }, [selectedBookId]);

  const handleGenerate = async () => {
    if (!selectedBookId) return;
    setGenerating(true);
    setError(null);
    try {
      await generateStudyCards(selectedBookId, { max_cards: 20 });
      onUpdated();
      if (selectedBookId) {
        const res = await getStudyDue(selectedBookId, 20);
        setDueCards(res.cards);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generate failed");
    } finally {
      setGenerating(false);
    }
  };

  const handleReview = async (card: StudyDueCard, grade: number) => {
    if (!selectedBookId) return;
    setError(null);
    try {
      await postStudyReview(selectedBookId, card.card_id, grade);
      setReviewingCard(null);
      setShowAnswer(false);
      const res = await getStudyDue(selectedBookId, 20);
      setDueCards(res.cards);
      onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed");
    }
  };

  const selectedBook = booksToUse.find((b) => b.book_id === selectedBookId);

  return (
    <section className="panel">
      <h2>Study (Cards)</h2>
      <p className="mb" style={{ fontSize: "0.9rem" }}>
        Per-book question cards. Generate from chunks, then review with spaced repetition.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="row mb">
        <select
          value={selectedBookId}
          onChange={(e) => onSelectBook(e.target.value)}
          disabled={loadingBooks}
          style={{ maxWidth: 220 }}
        >
          <option value="">Select book</option>
          {booksToUse.map((b) => (
            <option key={b.book_id} value={b.book_id}>
              {b.title} ({b.study.card_count} cards, {b.study.due_count} due)
            </option>
          ))}
        </select>
        <button
          className="primary"
          onClick={handleGenerate}
          disabled={generating || !selectedBookId}
        >
          {generating ? "Generating…" : "Generate cards"}
        </button>
      </div>
      {selectedBook && (
        <div className="mb" style={{ fontSize: "0.85rem" }}>
          {selectedBook.title}: {selectedBook.study.card_count} cards, {selectedBook.study.due_count} due
          {selectedBook.study.last_generated_at && (
            <span> · Last generated: {new Date(selectedBook.study.last_generated_at).toLocaleDateString()}</span>
          )}
        </div>
      )}
      {selectedBookId && (
        <div>
          <h3 style={{ fontSize: "0.9rem", marginBottom: 8 }}>Due cards</h3>
          {loadingDue ? (
            <p className="loading">Loading…</p>
          ) : dueCards.length === 0 ? (
            <p className="loading">
              {selectedBook?.study.card_count === 0
                ? "No cards yet. Generate some."
                : "No cards due right now."}
            </p>
          ) : reviewingCard ? (
            <div className="card-review">
              <div className="prompt">{reviewingCard.question}</div>
              {showAnswer ? (
                <>
                  <div className="answer-text mt" style={{ fontStyle: "italic" }}>{reviewingCard.answer}</div>
                  <div className="row mt" style={{ flexWrap: "wrap", gap: 4 }}>
                    {[0, 1, 2, 3, 4, 5].map((g) => (
                      <button
                        key={g}
                        className="secondary"
                        onClick={() => handleReview(reviewingCard, g)}
                        style={{ minWidth: 36 }}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <button className="secondary mt" onClick={() => setShowAnswer(true)}>
                  Show answer
                </button>
              )}
              <button className="secondary mt" style={{ marginLeft: 8 }} onClick={() => { setReviewingCard(null); setShowAnswer(false); }}>
                Skip
              </button>
            </div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0 }}>
              {dueCards.slice(0, 10).map((c) => (
                <li key={c.card_id} className="card-review" style={{ marginBottom: 8 }}>
                  <div className="prompt">{c.question}</div>
                  <button
                    className="secondary"
                    onClick={() => { setReviewingCard(c); setShowAnswer(false); }}
                  >
                    Review
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const CARD_TYPE_LABELS: Record<string, string> = {
  definition: "Definition",
  cloze: "Fill in the blank",
  list: "List",
  true_false: "True/False",
  short_answer: "Short answer",
  compare: "Compare",
};

function ExamPanel({
  selectedBookId,
  onSelectBook,
  books: booksProp,
  triggerGenerate,
  onTriggerConsumed,
}: {
  selectedBookId: string;
  onSelectBook: (id: string) => void;
  books: BookWithStudy[];
  triggerGenerate: string | null;
  onTriggerConsumed: () => void;
}) {
  const [localBooks, setLocalBooks] = useState<BookWithStudy[]>([]);
  const books = booksProp.length > 0 ? booksProp : localBooks;
  const [loadingBooks, setLoadingBooks] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exam, setExam] = useState<ExamGenerateResponse | null>(null);
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const [grades, setGrades] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  const loadBooks = useCallback(async () => {
    setLoadingBooks(true);
    setError(null);
    try {
      const res = await getBooks();
      setLocalBooks(res.books ?? []);
      if (!selectedBookId && res.books?.[0]) onSelectBook(res.books[0].book_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load books");
    } finally {
      setLoadingBooks(false);
    }
  }, [onSelectBook, selectedBookId]);

  useEffect(() => {
    if (booksProp.length === 0) loadBooks();
  }, [booksProp.length, loadBooks]);

  useEffect(() => {
    if (!triggerGenerate) return;
    onSelectBook(triggerGenerate);
    onTriggerConsumed();
    setGenerating(true);
    setError(null);
    setExam(null);
    setRevealed(new Set());
    setGrades({});
    postExamGenerate(triggerGenerate, { exam_size: 20 })
      .then(setExam)
      .catch((e) => setError(e instanceof Error ? e.message : "Generate failed"))
      .finally(() => setGenerating(false));
  }, [triggerGenerate, onSelectBook, onTriggerConsumed]);

  const handleGenerate = async () => {
    if (!selectedBookId) return;
    setGenerating(true);
    setError(null);
    setExam(null);
    setRevealed(new Set());
    setGrades({});
    try {
      const res = await postExamGenerate(selectedBookId, { exam_size: 20 });
      setExam(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generate failed");
    } finally {
      setGenerating(false);
    }
  };

  const toggleReveal = (cardId: string) => {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(cardId)) next.delete(cardId);
      else next.add(cardId);
      return next;
    });
  };

  const setGrade = (cardId: string, grade: number) => {
    setGrades((prev) => ({ ...prev, [cardId]: grade }));
  };

  const selectedBook = books.find((b) => b.book_id === selectedBookId);

  return (
    <section className="panel">
      <h2>Practice Exam</h2>
      <p className="mb" style={{ fontSize: "0.9rem" }}>
        Generate an exam from a book. Reveal answers and optionally grade yourself.
      </p>
      {error && <p className="error mb">{error}</p>}
      <div className="row mb">
        <select
          value={selectedBookId}
          onChange={(e) => onSelectBook(e.target.value)}
          disabled={loadingBooks}
          style={{ maxWidth: 220 }}
        >
          <option value="">Select book</option>
          {books.map((b) => (
            <option key={b.book_id} value={b.book_id}>
              {b.title} ({b.chunk_count} chunks)
            </option>
          ))}
        </select>
        <button
          className="primary"
          onClick={handleGenerate}
          disabled={generating || !selectedBookId}
        >
          {generating ? "Generating…" : "Generate practice exam (20)"}
        </button>
      </div>
      {exam && (
        <div className="exam-block">
          <h3 style={{ fontSize: "0.95rem", marginBottom: 8 }}>{exam.title}</h3>
          {exam.meta.counts_by_type && Object.keys(exam.meta.counts_by_type).length > 0 && (
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: 12 }}>
              {Object.entries(exam.meta.counts_by_type)
                .map(([t, n]) => `${CARD_TYPE_LABELS[t] ?? t}: ${n}`)
                .join(" · ")}
            </p>
          )}
          {(() => {
            const byType = exam.exam.questions.reduce<Record<string, ExamQuestion[]>>((acc, q) => {
              const t = q.card_type;
              if (!acc[t]) acc[t] = [];
              acc[t].push(q);
              return acc;
            }, {});
            const typeOrder = ["definition", "cloze", "list", "true_false", "short_answer", "compare"];
            let globalIdx = 0;
            return (
              <ul style={{ listStyle: "none", padding: 0 }}>
                {typeOrder.concat(Object.keys(byType).filter((t) => !typeOrder.includes(t))).map((t) => {
                  const qs = byType[t];
                  if (!qs?.length) return null;
                  return (
                    <li key={t} style={{ marginBottom: 16 }}>
                      <h4 style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: 8 }}>
                        {CARD_TYPE_LABELS[t] ?? t} ({qs.length})
                      </h4>
                      {qs.map((q) => {
                        globalIdx += 1;
                        const idx = globalIdx;
                        return (
                          <div key={q.card_id} className="exam-question" style={{ marginBottom: 12, padding: 12, border: "1px solid var(--border)", borderRadius: 6 }}>
                            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                              <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                                {idx}. {CARD_TYPE_LABELS[q.card_type] ?? q.card_type}
                              </span>
                            </div>
                <div className="prompt" style={{ marginTop: 6 }}>{q.prompt}</div>
                {revealed.has(q.card_id) ? (
                  <>
                    <div className="answer-text mt" style={{ fontStyle: "italic", padding: 8, background: "var(--bg)", borderRadius: 4 }}>
                      {q.answer}
                    </div>
                    {q.citations?.length > 0 && (
                      <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginTop: 6 }}>
                        {q.citations.map((c, i) => (
                          <span key={i}>{c.chunk_id}{i < q.citations!.length - 1 ? "; " : ""}</span>
                        ))}
                      </div>
                    )}
                    <div className="row mt" style={{ flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                      <span style={{ fontSize: "0.85rem", marginRight: 4 }}>Grade yourself:</span>
                      {[0, 1, 2, 3, 4, 5].map((g) => (
                        <button
                          key={g}
                          className={grades[q.card_id] === g ? "primary" : "secondary"}
                          onClick={() => setGrade(q.card_id, g)}
                          style={{ minWidth: 32, padding: "2px 6px" }}
                        >
                          {g}
                        </button>
                      ))}
                      {grades[q.card_id] !== undefined && (
                        <span style={{ marginLeft: 4, fontSize: "0.85rem" }}>✓</span>
                      )}
                    </div>
                    <button className="secondary mt" style={{ marginTop: 8 }} onClick={() => toggleReveal(q.card_id)}>
                      Hide answer
                    </button>
                  </>
                ) : (
                  <button className="secondary mt" onClick={() => toggleReveal(q.card_id)}>
                    Reveal answer
                  </button>
                )}
                          </div>
                        );
                      })}
                    </li>
                  );
                })}
              </ul>
            );
          })()}
        </div>
      )}
    </section>
  );
}

function StudyPanel({ catalog }: { catalog: CatalogResponse | null }) {
  const [minutes, setMinutes] = useState(30);
  const [book, setBook] = useState("");
  const [plan, setPlan] = useState<StudyPlanResponse | null>(null);
  const [due, setDue] = useState<DueCardsResponse | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [loadingDue, setLoadingDue] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewingCard, setReviewingCard] = useState<CardSummary | null>(null);
  const [userAnswer, setUserAnswer] = useState("");
  const [reviewResult, setReviewResult] = useState<{
    score: number;
    feedback: string;
    new_schedule: Record<string, unknown>;
  } | null>(null);

  const loadPlan = async () => {
    setLoadingPlan(true);
    setError(null);
    try {
      const res = await postPlan({ minutes, book: book || undefined });
      setPlan(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoadingPlan(false);
    }
  };

  const loadDue = async () => {
    setLoadingDue(true);
    setError(null);
    try {
      const res = await getDue();
      setDue(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoadingDue(false);
    }
  };

  useEffect(() => {
    loadDue();
  }, []);

  const handleReview = async () => {
    if (!reviewingCard || !userAnswer.trim()) return;
    setError(null);
    setReviewResult(null);
    try {
      const res = await postReview({
        card_id: reviewingCard.card_id,
        user_answer: userAnswer.trim(),
      });
      setReviewResult(res);
      loadDue();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    }
  };

  const finishReview = () => {
    setReviewingCard(null);
    setUserAnswer("");
    setReviewResult(null);
  };

  return (
    <section className="panel">
      <h2>Study</h2>

      <div className="row mb">
        <input
          type="number"
          min={1}
          max={240}
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value) || 30)}
          style={{ width: 80 }}
        />
        <span>minutes</span>
        <select
          value={book}
          onChange={(e) => setBook(e.target.value)}
          style={{ maxWidth: 180 }}
        >
          <option value="">All books</option>
          {catalog?.books.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name}
            </option>
          ))}
        </select>
        <button
          className="primary"
          onClick={loadPlan}
          disabled={loadingPlan}
        >
          {loadingPlan ? "Loading…" : "Get plan"}
        </button>
        <button className="secondary" onClick={loadDue} disabled={loadingDue}>
          {loadingDue ? "Loading…" : "Refresh due"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {plan && (
        <div className="plan-summary mb">
          <div className="plan-bucket">
            <div className="label">Review</div>
            <div className="count">{plan.review.cards?.length ?? 0}</div>
          </div>
          <div className="plan-bucket">
            <div className="label">Boost</div>
            <div className="count">{plan.boost.cards?.length ?? 0}</div>
          </div>
          <div className="plan-bucket">
            <div className="label">Quiz</div>
            <div className="count">{(plan.quiz as { n_questions?: number })?.n_questions ?? 0}</div>
          </div>
          <div className="plan-bucket">
            <div className="label">Gap boost</div>
            <div className="count">{plan.gap_boost.cards?.length ?? 0}</div>
          </div>
        </div>
      )}

      {reviewingCard ? (
        <div className="card-review">
          <div className="card-meta">
            {reviewingCard.book_name} · {reviewingCard.card_type}
          </div>
          <div className="prompt">{reviewingCard.prompt}</div>
          <textarea
            placeholder="Your answer..."
            value={userAnswer}
            onChange={(e) => setUserAnswer(e.target.value)}
            rows={3}
          />
          <div className="row mt">
            <button
              className="primary"
              onClick={handleReview}
              disabled={!userAnswer.trim()}
            >
              Submit
            </button>
            <button className="secondary" onClick={finishReview}>
              Skip
            </button>
          </div>
          {reviewResult && (
            <div className="feedback mt">
              <div className="score">Score: {reviewResult.score}</div>
              <p>{reviewResult.feedback}</p>
              <button className="secondary mt" onClick={finishReview}>
                Next card
              </button>
            </div>
          )}
        </div>
      ) : (
        <div>
          <h3 style={{ fontSize: "0.9rem", marginBottom: 8 }}>
            Due cards ({due?.due_count ?? 0})
          </h3>
          {due?.cards.length ? (
            due.cards.slice(0, 5).map((c) => (
              <div key={c.card_id} className="card-review">
                <div className="card-meta">{c.book_name}</div>
                <div className="prompt">{c.prompt}</div>
                <button
                  className="secondary"
                  onClick={() => setReviewingCard(c)}
                >
                  Review
                </button>
              </div>
            ))
          ) : (
            <p className="loading">No cards due.</p>
          )}
        </div>
      )}
    </section>
  );
}

function ProgressPanel() {
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getProgress();
      setProgress(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading && !progress) return <section className="panel"><h2>Progress</h2><p className="loading">Loading…</p></section>;
  if (error && !progress) return <section className="panel"><h2>Progress</h2><p className="error">{error}</p></section>;

  return (
    <section className="panel">
      <h2>Progress</h2>
      <button className="secondary mb" onClick={load} disabled={loading}>
        {loading ? "Refreshing…" : "Refresh"}
      </button>
      {progress && (
        <>
          <div className="mastery-bar">
            <div
              className="fill"
              style={{ width: `${Math.round(progress.overall_mastery * 100)}%` }}
            />
          </div>
          <div className="stats-grid">
            <div className="stat-card">
              <div className="value">{progress.total_cards}</div>
              <div className="label">Total cards</div>
            </div>
            <div className="stat-card">
              <div className="value">{progress.due_count}</div>
              <div className="label">Due</div>
            </div>
          </div>
          {Object.keys(progress.by_book).length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Book</th>
                  <th>Mastery</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(progress.by_book).map(([name, val]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{Math.round(val * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {progress.weakest_sections.length > 0 && (
            <div>
              <h3 style={{ fontSize: "0.85rem", marginBottom: 8 }}>
                Weakest sections
              </h3>
              <ul>
                {(progress.weakest_sections as string[]).slice(0, 5).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
