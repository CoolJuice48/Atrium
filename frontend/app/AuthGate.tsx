"use client";

import { useState } from "react";
import { useAuth } from "./AuthContext";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="app">
        <header className="header">
          <h1>Atrium</h1>
        </header>
        <main>
          <p className="loading">Loading…</p>
        </main>
      </div>
    );
  }

  if (user) {
    return <>{children}</>;
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Atrium</h1>
      </header>
      <main>
        <section className="panel auth-panel">
          <h2>{mode === "login" ? "Log in" : "Create account"}</h2>
          <form onSubmit={handleSubmit} className="auth-form">
            <div className="row mb">
              <label>
                Email
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  disabled={submitting}
                  style={{ display: "block", width: "100%", maxWidth: 280 }}
                />
              </label>
            </div>
            <div className="row mb">
              <label>
                Password
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  disabled={submitting}
                  style={{ display: "block", width: "100%", maxWidth: 280 }}
                />
                {mode === "register" && (
                  <span className="hint" style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                    Min 8 characters
                  </span>
                )}
              </label>
            </div>
            {error && <p className="error mb">{error}</p>}
            <div className="row mb">
              <button type="submit" className="primary" disabled={submitting}>
                {submitting ? "…" : mode === "login" ? "Log in" : "Register"}
              </button>
            </div>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
            >
              {mode === "login" ? "Create account" : "Already have an account? Log in"}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
