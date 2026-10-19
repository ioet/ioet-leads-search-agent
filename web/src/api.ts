/** Campaign API client — same-origin `/api/*` with cookie credentials. */

export type UserPublic = {
  user_id: string;
  email: string;
  role: string;
  status: string;
};

export type UserDirectoryEntry = {
  user_id: string;
  email: string;
  name: string;
};

export type IcpPublic = {
  icp_id: string;
  title: string;
  pdf_s3_uri?: string | null;
  icp_json_s3_uri: string;
  version?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type IcpRecord = Record<string, unknown>;

export type CompaniesFilterConfig = {
  employee_ranges: string[];
  hq_locations: string[];
  tech_stack: string[];
  recent_funding: string | null;
  skip_customers: boolean;
  skip_open_deals: boolean;
  skip_has_owner: boolean;
  skip_contacted_within_days: number | null;
};

export type HiringSignalConfig = {
  mode: "required" | "boost" | "ignore";
  role_categories: string[];
  seniorities: string[];
  min_open_eng_roles: number | null;
  posted_within_days: number | null;
  open_longer_than_days: number | null;
  job_keywords: string[];
  job_locations: string[];
  sources: string[];
};

export type DecisionMakersConfig = {
  personas: string[];
  email_requirement: string;
  phone_enrichment: string;
  skip_when_no_email: boolean;
  contacts_per_company: number;
};

export type HubspotOutputConfig = {
  if_company_exists: string;
  if_contact_exists: string;
  lifecycle_stage: string;
  lead_status: string;
  add_to_list: string | null;
  follow_up_task_days: number | null;
};

export type EmailDraftConfig = {
  offer: string;
  angle: string;
  tone: string;
  length: string;
  call_to_action: string;
  language: string;
  drafts_per_contact: number;
  save_as: string;
  extra_instructions: string;
};

export type CampaignConfig = {
  run_mode: "review" | "live" | "dry_run";
  email_owner?: boolean;
  companies_per_run: number;
  company_goal?: number | null;
  credit_budget_per_run?: number | null;
  companies_filter_config: CompaniesFilterConfig;
  hiring_signal_config: HiringSignalConfig;
  decision_makers_config: DecisionMakersConfig;
  hubspot_output_config: HubspotOutputConfig;
  email_draft_config: EmailDraftConfig;
};

export type CampaignPublic = {
  campaign_id: string;
  name: string;
  owner_user_id: string;
  owner_name?: string | null;
  icp_id: string;
  start_date?: string | null;
  end_date?: string | null;
  status: "draft" | "active" | "ended";
  config: CampaignConfig;
  companies_upserted?: number;
  created_at: string;
  updated_at: string;
};

export type SchedulePublic = {
  schedule_id: string;
  campaign_id: string;
  type: "once" | "recurring";
  expression: string;
  timezone: string;
  enabled: boolean;
  lh_schedule_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type CampaignRunPublic = {
  run_id: string;
  campaign_id: string;
  campaign_name: string;
  trigger: "manual" | "scheduled";
  status: "pending" | "running" | "completed" | "failed";
  started_at?: string | null;
  ended_at?: string | null;
  lh_wf_run_id?: string | null;
  result_summary?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

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

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) throw new Error(await parseError(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

// --- Auth ---

export async function signup(email: string, password: string): Promise<{ message: string }> {
  return api("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function verifyEmail(token: string): Promise<{ message: string }> {
  return api(`/auth/verify?token=${encodeURIComponent(token)}`, { method: "POST" });
}

export async function login(email: string, password: string): Promise<UserPublic> {
  return api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  await api("/auth/logout", { method: "POST" });
}

export async function me(): Promise<UserPublic> {
  return api("/auth/me");
}

export async function refreshSession(): Promise<UserPublic> {
  return api("/auth/refresh", { method: "POST" });
}

// --- ICPs ---

export async function listIcps(): Promise<IcpPublic[]> {
  return api("/icps");
}

export async function getIcpDocument(icpId: string): Promise<{
  icp: IcpRecord;
  errors?: unknown[];
}> {
  return api(`/icps/${icpId}/document`);
}

export async function extractIcp(file: File): Promise<{
  icp: IcpRecord;
  errors?: unknown[];
  upload_id?: string;
  source_filename?: string;
}> {
  const form = new FormData();
  form.append("file", file);
  return api("/icps/extract", { method: "POST", body: form });
}

export async function createIcp(payload: {
  title: string;
  icp: IcpRecord;
  upload_id?: string;
  source_filename?: string;
}): Promise<IcpPublic> {
  return api("/icps", { method: "POST", body: JSON.stringify(payload) });
}

export async function deleteIcp(icpId: string): Promise<void> {
  await api(`/icps/${icpId}`, { method: "DELETE" });
}

// --- Campaigns ---

export async function listCampaigns(): Promise<CampaignPublic[]> {
  return api("/campaigns");
}

export async function listUserDirectory(): Promise<UserDirectoryEntry[]> {
  return api("/users/directory");
}

export async function createCampaign(payload: {
  name: string;
  icp_id: string;
  owner_user_id?: string;
  start_date?: string | null;
  end_date?: string | null;
  status?: "draft" | "active" | "ended";
  config?: Partial<CampaignConfig> | CampaignConfig;
}): Promise<CampaignPublic> {
  return api("/campaigns", { method: "POST", body: JSON.stringify(payload) });
}

export async function updateCampaign(
  campaignId: string,
  payload: Partial<{
    name: string;
    icp_id: string;
    owner_user_id: string;
    start_date: string | null;
    end_date: string | null;
    status: "draft" | "active" | "ended";
    config: Partial<CampaignConfig> | CampaignConfig;
  }>,
): Promise<CampaignPublic> {
  return api(`/campaigns/${campaignId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteCampaign(campaignId: string): Promise<void> {
  await api(`/campaigns/${campaignId}`, { method: "DELETE" });
}

// --- Schedules ---

export async function listSchedules(campaignId: string): Promise<SchedulePublic[]> {
  return api(`/campaigns/${campaignId}/schedules`);
}

export async function createSchedule(
  campaignId: string,
  payload: {
    type: "once" | "recurring";
    expression: string;
    timezone?: string;
    enabled?: boolean;
  },
): Promise<SchedulePublic> {
  return api(`/campaigns/${campaignId}/schedules`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateSchedule(
  scheduleId: string,
  payload: Partial<{ expression: string; timezone: string; enabled: boolean }>,
): Promise<SchedulePublic> {
  return api(`/schedules/${scheduleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteSchedule(scheduleId: string): Promise<void> {
  await api(`/schedules/${scheduleId}`, { method: "DELETE" });
}

// --- Runs ---

export async function listRuns(campaignId: string): Promise<CampaignRunPublic[]> {
  return api(`/campaigns/${campaignId}/runs`);
}

export async function startTestRun(payload: {
  name: string;
  icp_id: string;
  config: CampaignConfig;
}): Promise<{ lh_wf_run_id: string; dry_run: boolean; companies_per_run: number }> {
  return api("/campaigns/test-run", {
    method: "POST",
    body: JSON.stringify({
      ...payload,
      config: { ...payload.config, run_mode: "dry_run" },
    }),
  });
}

export async function createRun(
  campaignId: string,
  trigger: "manual" | "scheduled" = "manual",
): Promise<CampaignRunPublic> {
  return api(`/campaigns/${campaignId}/runs`, {
    method: "POST",
    body: JSON.stringify({ trigger }),
  });
}
