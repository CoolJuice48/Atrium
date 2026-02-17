"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getBookOutline,
  postScopedSummary,
  type OutlineItem,
  type OutlineResponse,
  type ScopedSummaryResponse,
} from "./api";

interface ScopedSummaryPanelProps {
  bookId: string;
  bookTitle: string;
}

export function ScopedSummaryPanel({ bookId, bookTitle }: ScopedSummaryPanelProps) {
  const [outline, setOutline] = useState<OutlineResponse | null>(null);
  const [loadingOutline, setLoadingOutline] = useState(false);
  const [outlineError, setOutlineError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [expandedChapters, setExpandedChapters] = useState<Set<string>>(new Set());
  const [generating, setGenerating] = useState(false);
  const [summary, setSummary] = useState<ScopedSummaryResponse | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const fetchOutline = useCallback(async () => {
    if (!bookId) return;
    setLoadingOutline(true);
    setOutlineError(null);
    try {
      const res = await getBookOutline(bookId);
      setOutline(res);
      setExpandedChapters(new Set(res.items.filter((i) => i.level === 1).map((i) => i.id)));
    } catch (e) {
      setOutlineError(e instanceof Error ? e.message : "Failed to load outline");
      setOutline(null);
    } finally {
      setLoadingOutline(false);
    }
  }, [bookId]);

  useEffect(() => {
    fetchOutline();
  }, [fetchOutline]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleExpand = (id: string) => {
    setExpandedChapters((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllChapters = () => {
    if (!outline) return;
    const chapterIds = outline.items.filter((i) => i.level === 1).map((i) => i.id);
    setSelectedIds(new Set(chapterIds));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  const handleGenerate = async () => {
    if (!bookId || !outline || selectedIds.size === 0) return;
    setGenerating(true);
    setSummaryError(null);
    setSummary(null);
    try {
      const res = await postScopedSummary(bookId, {
        outline_id: outline.outline_id,
        scope: { item_ids: Array.from(selectedIds) },
        options: { bullets_target: 10, max_pages: 80 },
      });
      setSummary(res);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Summary generation failed";
      setSummaryError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const getScopePill = () => {
    if (!outline || selectedIds.size === 0) return null;
    const selected = outline.items.filter((i) => selectedIds.has(i.id));
    const chapters = selected.filter((i) => i.level === 1);
    const sections = selected.filter((i) => i.level === 2);
    const parts: string[] = [];
    if (chapters.length > 0) parts.push(`${chapters.length} chapter(s)`);
    if (sections.length > 0) parts.push(`${sections.length} section(s)`);
    return parts.length > 0 ? parts.join(", ") : null;
  };

  const renderItem = (item: OutlineItem, depth: number) => {
    const isChapter = item.level === 1;
    const children = outline!.items.filter((i) => i.parent_id === item.id);
    const hasChildren = children.length > 0;
    const isExpanded = expandedChapters.has(item.id);
    const isChecked = selectedIds.has(item.id);

    return (
      <div key={item.id} style={{ marginLeft: depth * 16, marginBottom: 4 }}>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            cursor: "pointer",
            fontSize: isChapter ? "0.95rem" : "0.85rem",
          }}
        >
          {hasChildren && (
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                toggleExpand(item.id);
              }}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                fontSize: "0.8rem",
                width: 20,
              }}
            >
              {isExpanded ? "▼" : "▶"}
            </button>
          )}
          {!hasChildren && <span style={{ width: 20 }} />}
          <input
            type="checkbox"
            checked={isChecked}
            onChange={() => toggleSelect(item.id)}
          />
          <span>
            {item.title}
            <span style={{ color: "var(--text-secondary)", fontSize: "0.8rem", marginLeft: 4 }}>
              (pp. {item.start_page}–{item.end_page})
            </span>
          </span>
        </label>
        {hasChildren && isExpanded && (
          <div style={{ marginTop: 4 }}>
            {children.map((c) => renderItem(c, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  if (!bookId) return null;

  return (
    <section className="panel">
      <h2>Scoped Summary</h2>
      <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: 12 }}>
        Choose chapters or sections to summarize. Avoid summarizing entire textbooks.
      </p>

      {loadingOutline && <p className="loading">Loading outline…</p>}
      {outlineError && <p className="error">{outlineError}</p>}

      {outline && outline.items.length > 0 && (
        <>
          <div style={{ marginBottom: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button type="button" className="secondary" onClick={selectAllChapters}>
              Select all chapters
            </button>
            <button type="button" className="secondary" onClick={clearSelection}>
              Clear
            </button>
          </div>

          <div
            style={{
              maxHeight: 280,
              overflowY: "auto",
              border: "1px solid var(--border)",
              borderRadius: 6,
              padding: 12,
              marginBottom: 12,
              background: "var(--bg-secondary)",
            }}
          >
            {outline.items
              .filter((i) => !i.parent_id)
              .map((item) => renderItem(item, 0))}
          </div>

          {getScopePill() && (
            <p style={{ fontSize: "0.85rem", marginBottom: 8 }}>
              <strong>Scope:</strong> {getScopePill()}
            </p>
          )}

          <button
            className="primary"
            onClick={handleGenerate}
            disabled={generating || selectedIds.size === 0}
          >
            {generating ? "Generating…" : "Generate summary"}
          </button>

          {selectedIds.size === 0 && (
            <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: 8 }}>
              Select at least one chapter or section.
            </p>
          )}
        </>
      )}

      {outline && outline.items.length === 0 && !loadingOutline && (
        <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
          No outline available. The book may not have chapter structure.
        </p>
      )}

      {summaryError && <p className="error mt">{summaryError}</p>}

      {summary && (
        <div className="answer-block mt" style={{ marginTop: 16 }}>
          <div className="answer-text" style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
            {summary.summary_markdown}
          </div>
          {summary.citations.length > 0 && (
            <div className="sources mt">
              <h3>Sources</h3>
              {summary.citations.map((c, i) => (
                <div key={i} className="source-item">
                  {c}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
