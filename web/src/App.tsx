import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  extractIcp,
  getIcp,
  IcpRecord,
  publishIcp,
  validateIcp,
} from "./api";
import "./App.css";

const MAX_BYTES = 5 * 1024 * 1024;

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function asString(record: IcpRecord, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function setField(record: IcpRecord, key: string, value: string): IcpRecord {
  return { ...record, [key]: value };
}

export default function App() {
  const [current, setCurrent] = useState<IcpRecord | null>(null);
  const [currentMeta, setCurrentMeta] = useState("");
  const [draft, setDraft] = useState<IcpRecord | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");
  const [schemaErrors, setSchemaErrors] = useState<unknown[]>([]);
  const [uploadId, setUploadId] = useState<string>();
  const [sourceFilename, setSourceFilename] = useState<string>();
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState<"load" | "extract" | "validate" | "publish" | null>(
    "load",
  );
  const [message, setMessage] = useState<{ kind: "ok" | "error" | "warn"; text: string }>();

  async function refreshCurrent() {
    const response = await getIcp();
    setCurrent(response.icp);
    const bits = [
      asString(response.icp, "version") && `version ${asString(response.icp, "version")}`,
      response.s3_version_id && `S3 ${response.s3_version_id}`,
      response.last_modified,
    ].filter(Boolean);
    setCurrentMeta(bits.join(" · "));
  }

  useEffect(() => {
    refreshCurrent()
      .catch((err: Error) => setMessage({ kind: "error", text: err.message }))
      .finally(() => setBusy(null));
  }, []);

  function applyDraft(icp: IcpRecord, extra?: { uploadId?: string; filename?: string }) {
    setDraft(icp);
    setJsonText(pretty(icp));
    setJsonError("");
    if (extra?.uploadId) setUploadId(extra.uploadId);
    if (extra?.filename) setSourceFilename(extra.filename);
  }

  function onJsonChange(text: string) {
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as IcpRecord;
      setDraft(parsed);
      setJsonError("");
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : "Invalid JSON");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("pdf") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      setMessage({ kind: "error", text: "Choose a PDF first." });
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setMessage({ kind: "error", text: "Only PDF files are accepted." });
      return;
    }
    if (file.size > MAX_BYTES) {
      setMessage({ kind: "error", text: "PDF must be 5 MB or smaller." });
      return;
    }

    setBusy("extract");
    setMessage(undefined);
    setFileName(file.name);
    try {
      const response = await extractIcp(file);
      applyDraft(response.icp, {
        uploadId: response.upload_id,
        filename: response.source_filename || file.name,
      });
      setSchemaErrors(response.errors || []);
      setMessage({
        kind: response.errors?.length ? "warn" : "ok",
        text: response.errors?.length
          ? "Extracted a draft with schema issues — fix them before publishing."
          : "Extracted a valid ICP draft. Review, then publish.",
      });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onValidate() {
    if (!draft || jsonError) return;
    setBusy("validate");
    setMessage(undefined);
    try {
      const response = await validateIcp(draft);
      setSchemaErrors(response.errors || []);
      setMessage({
        kind: response.ok ? "ok" : "warn",
        text: response.ok ? "Draft matches the ICP schema." : "Schema errors remain.",
      });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onPublish() {
    if (!draft || jsonError) return;
    setBusy("publish");
    setMessage(undefined);
    try {
      const response = await publishIcp({
        icp: draft,
        upload_id: uploadId,
        source_filename: sourceFilename || fileName,
      });
      setSchemaErrors([]);
      await refreshCurrent();
      setMessage({
        kind: "ok",
        text: `Published version ${asString(response.icp, "version")}${
          response.s3_version_id ? ` (S3 ${response.s3_version_id})` : ""
        }.`,
      });
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  const canPublish = useMemo(
    () => Boolean(draft) && !jsonError && busy === null,
    [draft, jsonError, busy],
  );

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <h1>ICP admin</h1>
          <p>Upload a BD PDF, review the extracted JSON, and publish a new S3 version.</p>
        </div>
        <p className="meta">{currentMeta || "No published ICP loaded yet"}</p>
      </header>

      {message ? <div className={`banner ${message.kind}`}>{message.text}</div> : null}

      <section className="card">
        <h2>Current published ICP</h2>
        {current ? (
          <p className="hint">
            {asString(current, "campaign") || "—"} · source {asString(current, "source") || "—"} ·
            prepared by {asString(current, "prepared_by") || "—"}
          </p>
        ) : (
          <p className="hint">{busy === "load" ? "Loading…" : "Nothing loaded."}</p>
        )}
      </section>

      <form className="card" onSubmit={onSubmit}>
        <h2>Extract from PDF</h2>
        <label className="drop">
          <input type="file" name="pdf" accept="application/pdf,.pdf" />
          <p>
            <strong>{fileName || "Choose a PDF"}</strong>
            <br />
            Max 5 MB. Submit to extract fields via Lambda.
          </p>
        </label>
        <div className="row">
          <button type="submit" disabled={busy !== null}>
            {busy === "extract" ? "Extracting…" : "Extract ICP"}
          </button>
        </div>
      </form>

      {draft ? (
        <section className="card">
          <h2>Review draft</h2>
          <div className="fields">
            <label>
              Version
              <input
                value={asString(draft, "version")}
                onChange={(event) => {
                  const next = setField(draft, "version", event.target.value);
                  applyDraft(next);
                }}
              />
            </label>
            <label>
              Campaign
              <input
                value={asString(draft, "campaign")}
                onChange={(event) => {
                  const next = setField(draft, "campaign", event.target.value);
                  applyDraft(next);
                }}
              />
            </label>
            <label>
              Prepared by
              <input
                value={asString(draft, "prepared_by")}
                onChange={(event) => {
                  const next = setField(draft, "prepared_by", event.target.value);
                  applyDraft(next);
                }}
              />
            </label>
            <label>
              Source
              <input
                value={asString(draft, "source")}
                onChange={(event) => {
                  const next = setField(draft, "source", event.target.value);
                  applyDraft(next);
                }}
              />
            </label>
          </div>
          <textarea
            className="editor"
            value={jsonText}
            onChange={(event) => onJsonChange(event.target.value)}
            spellCheck={false}
          />
          {jsonError ? <div className="banner error">{jsonError}</div> : null}
          {schemaErrors.length ? (
            <div className="banner warn">{pretty(schemaErrors)}</div>
          ) : null}
          <div className="row">
            <button type="button" className="secondary" onClick={onValidate} disabled={!canPublish}>
              {busy === "validate" ? "Validating…" : "Validate"}
            </button>
            <button type="button" onClick={onPublish} disabled={!canPublish}>
              {busy === "publish" ? "Publishing…" : "Publish to S3"}
            </button>
          </div>
        </section>
      ) : null}
    </main>
  );
}
