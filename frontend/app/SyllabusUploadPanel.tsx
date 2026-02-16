"use client";

import { useState, useRef } from "react";
import {
  postSyllabusUpload,
  postPlanGenerateFromFeatures,
} from "./api";
import { encryptSyllabus } from "./syllabusCrypto";
import {
  extractTextFromFile,
  extractFeaturesFromText,
  type SyllabusFeatures,
} from "./syllabusFeatures";

function buf2b64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
    binary += String.fromCharCode.apply(null, Array.from(chunk));
  }
  return btoa(binary);
}

export function SyllabusUploadPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [pathId, setPathId] = useState("default");
  const [uploading, setUploading] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [result, setResult] = useState<{
    syllabusId: string;
    planId?: string;
    summary?: Record<string, unknown>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    setFile(f ?? null);
    setResult(null);
    setError(null);
  };

  const handleUpload = async () => {
    if (!file || !password) return;
    setUploading(true);
    setError(null);
    setResult(null);
    const start = Date.now();
    const timer = setInterval(() => setElapsedMs(Date.now() - start), 200);

    try {
      const fileContent = await file.arrayBuffer();

      const { ciphertext, wrappedUdk, kdfParams } = await encryptSyllabus(
        fileContent,
        password
      );

      const formData = new FormData();
      formData.append("file", new Blob([ciphertext]), file.name + ".enc");
      formData.append("filename", file.name);
      formData.append("mime", file.type || "application/octet-stream");
      formData.append("size_bytes", String(file.size));
      formData.append("wrapped_udk", buf2b64(wrappedUdk));
      formData.append("kdf_params", JSON.stringify(kdfParams));

      const uploadRes = await postSyllabusUpload(formData);
      const syllabusId = uploadRes.syllabus_id;

      let features: SyllabusFeatures = { topics: [], weeks: [], textbooks: [] };
      try {
        const text = await extractTextFromFile(file);
        if (text) features = extractFeaturesFromText(text);
      } catch {
        // Feature extraction optional
      }

      const planRes = await postPlanGenerateFromFeatures({
        syllabus_id: syllabusId,
        path_id: pathId,
        features: {
          topics: features.topics,
          weeks: features.weeks,
          textbooks: features.textbooks,
        },
      });

      setResult({
        syllabusId,
        planId: planRes.plan_id,
        summary: planRes.summary,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      clearInterval(timer);
      setUploading(false);
      setElapsedMs(0);
    }
  };

  return (
    <section className="panel syllabus-upload-panel">
      <h2>Upload syllabus</h2>
      <p className="mb" style={{ fontSize: "0.9rem" }}>
        Zero-knowledge: your syllabus is encrypted locally. The server stores
        only ciphertext and cannot read it.
      </p>
      <div className="row mb">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,application/pdf,text/plain"
          onChange={handleFileChange}
          disabled={uploading}
        />
        {file && (
          <span style={{ marginLeft: 8, fontSize: "0.9rem" }}>{file.name}</span>
        )}
      </div>
      <div className="row mb">
        <label>
          Password (to encrypt)
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
            disabled={uploading}
            style={{ display: "block", width: 200, marginTop: 4 }}
          />
        </label>
      </div>
      <div className="row mb">
        <label>
          Path ID
          <input
            type="text"
            value={pathId}
            onChange={(e) => setPathId(e.target.value)}
            disabled={uploading}
            style={{ display: "block", width: 120, marginTop: 4 }}
          />
        </label>
      </div>
      <div className="row mb">
        <button
          className="primary"
          onClick={handleUpload}
          disabled={uploading || !file || !password}
        >
          {uploading ? "Uploading…" : "Upload & generate plan"}
        </button>
        {uploading && (
          <span className="build-timer" style={{ marginLeft: 12 }}>
            {Math.round(elapsedMs / 1000)}s
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="success mt">
          <p>Syllabus uploaded. Plan generated.</p>
          <p style={{ fontSize: "0.9rem", marginTop: 4 }}>
            Syllabus ID: {result.syllabusId}
            {result.planId && ` · Plan ID: ${result.planId}`}
          </p>
          {result.summary && Object.keys(result.summary).length > 0 && (
            <pre
              style={{
                marginTop: 8,
                fontSize: "0.8rem",
                background: "var(--bg)",
                padding: 8,
                borderRadius: 4,
                overflow: "auto",
              }}
            >
              {JSON.stringify(result.summary, null, 2)}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
