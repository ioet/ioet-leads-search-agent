export type IcpRecord = Record<string, unknown>;

export type IcpApiResponse = {
  icp: IcpRecord;
  errors?: unknown[];
  s3_version_id?: string | null;
  last_modified?: string | null;
  upload_id?: string;
  source_filename?: string;
  ok?: boolean;
};

const API_BASE = (import.meta.env.VITE_ICP_API_URL || "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return JSON.stringify(detail, null, 2);
    return JSON.stringify(body, null, 2);
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

export async function getIcp(): Promise<IcpApiResponse> {
  const response = await fetch(apiUrl("/v1/icp"));
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function extractIcp(file: File): Promise<IcpApiResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl("/v1/icp/extract"), {
    method: "POST",
    body: form,
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function validateIcp(icp: IcpRecord): Promise<IcpApiResponse> {
  const response = await fetch(apiUrl("/v1/icp/validate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ icp }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function publishIcp(payload: {
  icp: IcpRecord;
  upload_id?: string;
  source_filename?: string;
}): Promise<IcpApiResponse> {
  const response = await fetch(apiUrl("/v1/icp"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
