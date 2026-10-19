import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createIcp,
  deleteIcp,
  extractIcp,
  getIcpDocument,
  IcpPublic,
  IcpRecord,
  listIcps,
} from "./api";

const MAX_BYTES = 5 * 1024 * 1024;

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

type Props = {
  onMessage: (msg: { kind: "ok" | "error" | "warn"; text: string } | undefined) => void;
};

export default function IcpTab({ onMessage }: Props) {
  const [icps, setIcps] = useState<IcpPublic[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [document, setDocument] = useState<IcpRecord | null>(null);
  const [draft, setDraft] = useState<IcpRecord | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState("");
  const [title, setTitle] = useState("");
  const [uploadId, setUploadId] = useState<string>();
  const [sourceFilename, setSourceFilename] = useState<string>();
  const [schemaErrors, setSchemaErrors] = useState<unknown[]>([]);
  const [busy, setBusy] = useState<string | null>("load");

  const refresh = useCallback(async () => {
    const rows = await listIcps();
    setIcps(rows);
  }, []);

  useEffect(() => {
    refresh()
      .catch((err: Error) => onMessage({ kind: "error", text: err.message }))
      .finally(() => setBusy(null));
  }, [refresh, onMessage]);

  async function selectIcp(icpId: string) {
    setBusy("load");
    setSelectedId(icpId);
    onMessage(undefined);
    try {
      const meta = icps.find((row) => row.icp_id === icpId);
      const doc = await getIcpDocument(icpId);
      setDocument(doc.icp);
      setDraft(null);
      setJsonText("");
      setTitle(meta?.title || "");
      setSchemaErrors(doc.errors || []);
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  function applyDraft(icp: IcpRecord) {
    setDraft(icp);
    setJsonText(pretty(icp));
    setJsonError("");
  }

  function onJsonChange(text: string) {
    setJsonText(text);
    try {
      applyDraft(JSON.parse(text) as IcpRecord);
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : "Invalid JSON");
    }
  }

  async function onExtract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("pdf") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      onMessage({ kind: "error", text: "Choose a PDF first." });
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      onMessage({ kind: "error", text: "Only PDF files are accepted." });
      return;
    }
    if (file.size > MAX_BYTES) {
      onMessage({ kind: "error", text: "PDF must be 5 MB or smaller." });
      return;
    }
    setBusy("extract");
    onMessage(undefined);
    try {
      const response = await extractIcp(file);
      applyDraft(response.icp);
      setUploadId(response.upload_id);
      setSourceFilename(response.source_filename || file.name);
      setTitle(file.name.replace(/\.pdf$/i, ""));
      setSchemaErrors(response.errors || []);
      setSelectedId(undefined);
      setDocument(null);
      onMessage({
        kind: response.errors?.length ? "warn" : "ok",
        text: response.errors?.length
          ? "Extracted a draft with schema issues — fix before saving."
          : "Extracted a valid ICP draft. Review, then save.",
      });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onSave() {
    if (!draft || jsonError || !title.trim()) {
      onMessage({ kind: "error", text: "Title and valid JSON are required." });
      return;
    }
    setBusy("save");
    onMessage(undefined);
    try {
      const created = await createIcp({
        title: title.trim(),
        icp: draft,
        upload_id: uploadId,
        source_filename: sourceFilename,
      });
      await refresh();
      setSelectedId(created.icp_id);
      setDocument(draft);
      setDraft(null);
      setJsonText("");
      setUploadId(undefined);
      onMessage({ kind: "ok", text: `Saved ICP “${created.title}”.` });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(icpId: string) {
    if (!window.confirm("Delete this ICP?")) return;
    setBusy("delete");
    try {
      await deleteIcp(icpId);
      if (selectedId === icpId) {
        setSelectedId(undefined);
        setDocument(null);
      }
      await refresh();
      onMessage({ kind: "ok", text: "ICP deleted." });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="tab-grid">
      <section className="card">
        <h2>Your ICPs</h2>
        {icps.length === 0 ? (
          <p className="hint">{busy === "load" ? "Loading…" : "No ICPs yet."}</p>
        ) : (
          <ul className="list">
            {icps.map((row) => (
              <li key={row.icp_id} className={selectedId === row.icp_id ? "active" : ""}>
                <button type="button" className="list-main" onClick={() => selectIcp(row.icp_id)}>
                  <strong>{row.title}</strong>
                  <span>{row.version || "—"} · {row.updated_at.slice(0, 10)}</span>
                </button>
                <button
                  type="button"
                  className="secondary danger"
                  onClick={() => onDelete(row.icp_id)}
                  disabled={busy !== null}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="stack">
        <form className="card" onSubmit={onExtract}>
          <h2>Extract from PDF</h2>
          <label className="drop">
            <input type="file" name="pdf" accept="application/pdf,.pdf" />
            <p>
              <strong>Choose a PDF</strong>
              <br />
              Max 5 MB. Extract fields via Bedrock, then save as a new ICP.
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
            <h2>New ICP draft</h2>
            <label>
              Title
              <input value={title} onChange={(e) => setTitle(e.target.value)} required />
            </label>
            <textarea
              className="editor"
              value={jsonText}
              onChange={(e) => onJsonChange(e.target.value)}
              spellCheck={false}
            />
            {jsonError ? <div className="banner error">{jsonError}</div> : null}
            {schemaErrors.length ? (
              <div className="banner warn">{pretty(schemaErrors)}</div>
            ) : null}
            <div className="row">
              <button type="button" onClick={onSave} disabled={busy !== null || !!jsonError}>
                {busy === "save" ? "Saving…" : "Save ICP"}
              </button>
            </div>
          </section>
        ) : null}

        {document && !draft ? (
          <section className="card">
            <h2>Published document</h2>
            <p className="hint">{title}</p>
            <pre className="editor readonly">{pretty(document)}</pre>
          </section>
        ) : null}
      </div>
    </div>
  );
}
