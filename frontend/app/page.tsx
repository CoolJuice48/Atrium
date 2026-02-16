"use client";

import { useState, useEffect } from "react";
import {
  getHealth,
  getCatalog,
  postQuery,
  postCardsFromLastAnswer,
  postPlan,
  getDue,
  postReview,
  getProgress,
  type CatalogResponse,
  type QueryResponse,
  type StudyPlanResponse,
  type DueCardsResponse,
  type ProgressResponse,
  type CardSummary,
} from "./api";

export default function Home() {
  const [apiStatus, setApiStatus] = useState<"ok" | "err" | null>(null);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);

  useEffect(() => {
    getHealth()
      .then(() => setApiStatus("ok"))
      .catch(() => setApiStatus("err"));
    getCatalog()
      .then(setCatalog)
      .catch(() => setCatalog(null));
  }, []);

  return (
    <div className="app">
      <header className="header">
        <h1>Atrium</h1>
        {apiStatus && (
          <span className={`status-chip ${apiStatus}`}>
            {apiStatus === "ok" ? "API connected" : "API offline"}
          </span>
        )}
      </header>

      <main>
        <AskPanel catalog={catalog} />
        <StudyPanel catalog={catalog} />
        <ProgressPanel />
      </main>
    </div>
  );
}

function AskPanel({ catalog }: { catalog: CatalogResponse | null }) {
  const [question, setQuestion] = useState("");
  const [book, setBook] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [cardsCreated, setCardsCreated] = useState<number | null>(null);

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

  return (
    <section className="panel">
      <h2>Ask</h2>
      <div className="row mb">
        <textarea
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
          onChange={(e) => setBook(e.target.value)}
          disabled={loading}
          style={{ maxWidth: 200 }}
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
              className="secondary"
              onClick={handleCreateCards}
              disabled={loading}
            >
              Generate study cards from answer
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
