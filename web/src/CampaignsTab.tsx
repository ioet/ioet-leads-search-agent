import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CampaignConfig,
  CampaignPublic,
  createCampaign,
  deleteCampaign,
  IcpPublic,
  listCampaigns,
  listIcps,
  listUserDirectory,
  startTestRun,
  updateCampaign,
  UserDirectoryEntry,
  UserPublic,
} from "./api";

const EMPLOYEE_BANDS = ["1–10", "11–50", "51–200", "201–500", "501–1k", "1k+"];
const HQ_LOCATIONS = ["United States", "Canada", "United Kingdom", "EU"];
const ROLE_CATEGORIES = [
  "Backend",
  "Frontend",
  "Full-stack",
  "DevOps / Platform",
  "Data / ML",
  "Mobile",
  "QA / SDET",
  "Engineering management",
];
const SENIORITIES = ["Junior", "Mid", "Senior", "Staff", "Principal", "Director+"];
const JOB_SOURCES = [
  { id: "apollo", label: "Apollo job postings" },
  { id: "company_website", label: "Company careers page" },
];
const PERSONA_CHOICES = [
  "CTO",
  "VP Engineering",
  "Head of Engineering",
  "Director of Engineering",
  "Engineering Manager",
  "Founder / CEO (under 50 people)",
  "Head of Talent / Recruiting",
  "VP Product",
  "Head of Data",
];

const CREDIT_PER_CONTACT = 1;
const CREDIT_PER_PHONE = 8;

const RUN_MODE_HELP: Record<"review" | "live" | "dry_run", string> = {
  review: "Runs the search and drafts. Nothing is written to HubSpot.",
  live: "Writes companies, contacts, and notes to HubSpot.",
  dry_run: "Runs the search and drafts, writes nothing, spends no enrichment credits.",
};

type Props = {
  currentUser: UserPublic;
  onMessage: (msg: { kind: "ok" | "error" | "warn"; text: string } | undefined) => void;
  onOpenRuns: (campaignId: string) => void;
};

function defaultConfig(): CampaignConfig {
  return {
    run_mode: "dry_run",
    email_owner: true,
    companies_per_run: 25,
    company_goal: null,
    credit_budget_per_run: null,
    companies_filter_config: {
      employee_ranges: ["51–200", "201–500"],
      hq_locations: ["United States"],
      tech_stack: [],
      recent_funding: "any",
      skip_customers: true,
      skip_open_deals: true,
      skip_has_owner: true,
      skip_contacted_within_days: 60,
    },
    hiring_signal_config: {
      mode: "required",
      role_categories: ["Backend", "Full-stack"],
      seniorities: ["Senior", "Staff"],
      min_open_eng_roles: 1,
      posted_within_days: 30,
      open_longer_than_days: null,
      job_keywords: [],
      job_locations: [],
      sources: ["apollo", "company_website"],
    },
    decision_makers_config: {
      personas: ["CTO", "VP Engineering", "Head of Engineering"],
      email_requirement: "verified_only",
      phone_enrichment: "none",
      skip_when_no_email: true,
      contacts_per_company: 2,
    },
    hubspot_output_config: {
      if_company_exists: "add_job_note_only",
      if_contact_exists: "skip",
      lifecycle_stage: "lead",
      lead_status: "new",
      add_to_list: null,
      follow_up_task_days: 2,
    },
    email_draft_config: {
      offer: "staff_augmentation",
      angle: "hiring_signal",
      tone: "consultative",
      length: "short",
      call_to_action: "15_minute_call",
      language: "en",
      drafts_per_contact: 1,
      save_as: "note",
      extra_instructions: "",
    },
  };
}

function optionalPositive(raw: string): number | null {
  if (!raw.trim()) return null;
  const value = Math.floor(Number(raw));
  return Number.isFinite(value) && value >= 1 ? value : null;
}

function csv(values: string[]): string {
  return values.join(", ");
}

function parseCsv(text: string): string[] {
  return text
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
}

function CsvField({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(() => csv(values));
  const focused = useRef(false);
  const serialized = csv(values);

  useEffect(() => {
    if (!focused.current) setText(serialized);
  }, [serialized]);

  return (
    <label>
      {label}
      <input
        value={text}
        placeholder={placeholder}
        onFocus={() => {
          focused.current = true;
        }}
        onBlur={() => {
          focused.current = false;
          const parsed = parseCsv(text);
          setText(csv(parsed));
          onChange(parsed);
        }}
        onChange={(e) => {
          const next = e.target.value;
          setText(next);
          onChange(parseCsv(next));
        }}
      />
    </label>
  );
}

function toggleIn(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function ChipField({
  legend,
  options,
  selected,
  onToggle,
}: {
  legend: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset className="chips">
      <legend>{legend}</legend>
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          className={selected.includes(opt) ? "chip on" : "chip"}
          onClick={() => onToggle(opt)}
        >
          {opt}
        </button>
      ))}
    </fieldset>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { id: T; label: string }[];
  onChange: (next: T) => void;
}) {
  return (
    <div className="segmented">
      {options.map((opt) => (
        <button
          key={opt.id}
          type="button"
          className={value === opt.id ? "seg on" : "seg"}
          aria-pressed={value === opt.id}
          onClick={() => onChange(opt.id)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function CampaignsTab({ currentUser, onMessage, onOpenRuns }: Props) {
  const [campaigns, setCampaigns] = useState<CampaignPublic[]>([]);
  const [icps, setIcps] = useState<IcpPublic[]>([]);
  const [owners, setOwners] = useState<UserDirectoryEntry[]>([]);
  const [editing, setEditing] = useState<CampaignPublic | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState<string | null>("load");

  const [name, setName] = useState("");
  const [ownerUserId, setOwnerUserId] = useState(currentUser.user_id);
  const [icpId, setIcpId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [config, setConfig] = useState<CampaignConfig>(defaultConfig);

  const refresh = useCallback(async () => {
    const [c, i, directory] = await Promise.all([
      listCampaigns(),
      listIcps(),
      listUserDirectory(),
    ]);
    setCampaigns(c);
    setIcps(i);
    setOwners(directory);
    if (!icpId && i[0]) setIcpId(i[0].icp_id);
  }, [icpId]);

  useEffect(() => {
    refresh()
      .catch((err: Error) => onMessage({ kind: "error", text: err.message }))
      .finally(() => setBusy(null));
  }, [refresh, onMessage]);

  function patchConfig(partial: Partial<CampaignConfig>) {
    setConfig((prev) => ({ ...prev, ...partial }));
  }

  function movePersona(index: number, delta: number) {
    const personas = [...config.decision_makers_config.personas];
    const target = index + delta;
    if (target < 0 || target >= personas.length) return;
    const [persona] = personas.splice(index, 1);
    personas.splice(target, 0, persona);
    patchConfig({
      decision_makers_config: { ...config.decision_makers_config, personas },
    });
  }

  function resetForm(campaign?: CampaignPublic | null) {
    if (campaign) {
      setEditing(campaign);
      setName(campaign.name);
      setOwnerUserId(campaign.owner_user_id || currentUser.user_id);
      setIcpId(campaign.icp_id);
      setStartDate(campaign.start_date || "");
      setEndDate(campaign.end_date || "");
      setConfig({
        ...defaultConfig(),
        ...campaign.config,
        companies_filter_config: {
          ...defaultConfig().companies_filter_config,
          ...(campaign.config.companies_filter_config || {}),
          recent_funding: campaign.config.companies_filter_config?.recent_funding || "any",
        },
        hiring_signal_config: {
          ...defaultConfig().hiring_signal_config,
          ...(campaign.config.hiring_signal_config || {}),
        },
        decision_makers_config: {
          ...defaultConfig().decision_makers_config,
          ...(campaign.config.decision_makers_config || {}),
        },
        hubspot_output_config: {
          ...defaultConfig().hubspot_output_config,
          ...(campaign.config.hubspot_output_config || {}),
          lifecycle_stage:
            campaign.config.hubspot_output_config?.lifecycle_stage === "suscriber"
              ? "subscriber"
              : campaign.config.hubspot_output_config?.lifecycle_stage || "lead",
          lead_status:
            campaign.config.hubspot_output_config?.lead_status === "attempted_to_contact"
              ? "ATTEMPTED_TO_CONTACT"
              : campaign.config.hubspot_output_config?.lead_status || "new",
        },
        email_draft_config: {
          ...defaultConfig().email_draft_config,
          ...(campaign.config.email_draft_config || {}),
          save_as:
            campaign.config.email_draft_config?.save_as === "contact_note"
              ? "note"
              : campaign.config.email_draft_config?.save_as || "note",
          angle:
            campaign.config.email_draft_config?.angle === "tech_stack"
              ? "stack_match"
              : campaign.config.email_draft_config?.angle || "hiring_signal",
        },
      });
    } else {
      setEditing(null);
      setName("");
      setOwnerUserId(currentUser.user_id);
      setIcpId(icps[0]?.icp_id || "");
      setStartDate("");
      setEndDate("");
      setConfig(defaultConfig());
    }
    setShowForm(true);
  }

  const contactsPerRun =
    config.companies_per_run * (config.decision_makers_config.contacts_per_company || 1);
  const phoneCredits =
    config.decision_makers_config.phone_enrichment === "none"
      ? 0
      : config.companies_per_run * CREDIT_PER_PHONE;
  const estCredits =
    contactsPerRun * CREDIT_PER_CONTACT + phoneCredits;
  const estMonthly = Math.round(estCredits * (52 / 12)); // weekly cadence assumption for estimate
  const creditBudget = config.credit_budget_per_run;
  const overCreditBudget =
    typeof creditBudget === "number" && creditBudget > 0 && estCredits > creditBudget;

  const selectedIcp = useMemo(
    () => icps.find((i) => i.icp_id === icpId),
    [icps, icpId],
  );

  async function saveCampaign(nextStatus: "draft" | "active") {
    if (!name.trim() || !icpId) {
      onMessage({ kind: "error", text: "Name and ICP are required." });
      return;
    }
    setBusy(nextStatus);
    onMessage(undefined);
    const payload = {
      name: name.trim(),
      icp_id: icpId,
      owner_user_id: ownerUserId || currentUser.user_id,
      status: nextStatus,
      start_date: startDate || null,
      end_date: endDate || null,
      config,
    };
    try {
      if (editing) {
        await updateCampaign(editing.campaign_id, payload);
        onMessage({
          kind: "ok",
          text: nextStatus === "draft" ? "Draft saved." : "Campaign updated.",
        });
      } else {
        await createCampaign(payload);
        onMessage({
          kind: "ok",
          text: nextStatus === "draft" ? "Draft saved." : "Campaign created.",
        });
      }
      setShowForm(false);
      setEditing(null);
      await refresh();
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    await saveCampaign("active");
  }

  async function onTestRun() {
    if (!icpId) {
      onMessage({ kind: "error", text: "Pick an ICP before starting a test run." });
      return;
    }
    setBusy("test");
    onMessage(undefined);
    try {
      const started = await startTestRun({
        name: name.trim() || "Unsaved test",
        icp_id: icpId,
        config,
      });
      onMessage({
        kind: "ok",
        text:
          `Test run started (${started.lh_wf_run_id}). ` +
          "Dry run only — the campaign was not saved and HubSpot was not written.",
      });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function setCampaignStatus(campaign: CampaignPublic, next: "draft" | "active" | "ended") {
    setBusy("status");
    try {
      await updateCampaign(campaign.campaign_id, { status: next });
      await refresh();
      onMessage({ kind: "ok", text: `Campaign marked ${next}.` });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(campaignId: string) {
    if (!window.confirm("Delete this campaign and its schedules?")) return;
    setBusy("delete");
    try {
      await deleteCampaign(campaignId);
      await refresh();
      onMessage({ kind: "ok", text: "Campaign deleted." });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  const icpTitle = (id: string) => icps.find((i) => i.icp_id === id)?.title || id.slice(0, 8);
  const ownerLabel = (campaign: CampaignPublic) =>
    campaign.owner_name ||
    owners.find((owner) => owner.user_id === campaign.owner_user_id)?.name ||
    "unassigned";
  const filt = config.companies_filter_config;
  const hire = config.hiring_signal_config;
  const dm = config.decision_makers_config;
  const hs = config.hubspot_output_config;
  const email = config.email_draft_config;

  return (
    <div className="stack">
      <div className="row between">
        <div>
          <h2 className="inline-title">Campaigns</h2>
          <p className="hint">
            Pick a published ICP, set filters and hiring signals, then schedule runs from the Runs tab.
          </p>
        </div>
        <button type="button" onClick={() => resetForm(null)} disabled={busy !== null}>
          New campaign
        </button>
      </div>

      {showForm ? (
        <div className="campaign-layout">
          <form className="stack" onSubmit={onSubmit}>
            {/* Campaign */}
            <section className="card">
              <h2>Campaign</h2>
              <p className="hint">Which ICP to prospect against.</p>
              <div className="fields">
                <label>
                  Campaign name
                  <input value={name} onChange={(e) => setName(e.target.value)} required />
                </label>
                <label>
                  Campaign owner
                  <select
                    value={ownerUserId}
                    onChange={(e) => setOwnerUserId(e.target.value)}
                    required
                  >
                    {owners.length === 0 ? (
                      <option value={currentUser.user_id}>{currentUser.email}</option>
                    ) : null}
                    {owners.length > 0 &&
                    ownerUserId &&
                    !owners.some((owner) => owner.user_id === ownerUserId) ? (
                      <option value={ownerUserId}>
                        {editing?.owner_name || ownerUserId}
                      </option>
                    ) : null}
                    {owners.map((owner) => (
                      <option key={owner.user_id} value={owner.user_id}>
                        {owner.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  ICP
                  <select value={icpId} onChange={(e) => setIcpId(e.target.value)} required>
                    {icps.length === 0 ? (
                      <option value="">No ICPs — create one first</option>
                    ) : null}
                    {icps.map((icp) => (
                      <option key={icp.icp_id} value={icp.icp_id}>
                        {icp.title}
                        {icp.version ? ` (${icp.version})` : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Start date
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                  />
                </label>
                <label>
                  End date
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                  />
                </label>
              </div>
            </section>

            {/* Schedule & volume */}
            <section className="card">
              <h2>Volume</h2>
              <p className="hint">
                How much each run pulls. Stop after is the HubSpot company total shown
                on the list. Reaching it does not stop scheduled runs. Create the
                schedule on the Runs tab after saving.
              </p>
              <div className="fields">
                <label>
                  Companies per run
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={config.companies_per_run}
                    onChange={(e) =>
                      patchConfig({ companies_per_run: Number(e.target.value) || 1 })
                    }
                  />
                </label>
                <label>
                  Contacts per company
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={dm.contacts_per_company}
                    onChange={(e) =>
                      patchConfig({
                        decision_makers_config: {
                          ...dm,
                          contacts_per_company: Number(e.target.value) || 1,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Stop after (companies, total)
                  <input
                    type="number"
                    min={1}
                    placeholder="No goal"
                    value={config.company_goal ?? ""}
                    onChange={(e) =>
                      patchConfig({ company_goal: optionalPositive(e.target.value) })
                    }
                  />
                </label>
                <label>
                  Apollo credit budget per run
                  <input
                    type="number"
                    min={1}
                    placeholder="No budget"
                    value={config.credit_budget_per_run ?? ""}
                    onChange={(e) =>
                      patchConfig({
                        credit_budget_per_run: optionalPositive(e.target.value),
                      })
                    }
                  />
                </label>
              </div>
            </section>

            {/* Company filters */}
            <section className="card">
              <h2>Company filters</h2>
              <p className="hint">Overrides applied on top of the ICP segment when searching Apollo.</p>
              <ChipField
                legend="Employee bands"
                options={EMPLOYEE_BANDS}
                selected={filt.employee_ranges}
                onToggle={(v) =>
                  patchConfig({
                    companies_filter_config: {
                      ...filt,
                      employee_ranges: toggleIn(filt.employee_ranges, v),
                    },
                  })
                }
              />
              <ChipField
                legend="HQ locations"
                options={HQ_LOCATIONS}
                selected={filt.hq_locations}
                onToggle={(v) =>
                  patchConfig({
                    companies_filter_config: {
                      ...filt,
                      hq_locations: toggleIn(filt.hq_locations, v),
                    },
                  })
                }
              />
              <div className="fields">
                <CsvField
                  label="Tech stack (comma-separated)"
                  values={filt.tech_stack}
                  placeholder="React, AWS, Kubernetes"
                  onChange={(tech_stack) =>
                    patchConfig({
                      companies_filter_config: { ...filt, tech_stack },
                    })
                  }
                />
                <label>
                  Recent funding
                  <select
                    value={filt.recent_funding || "any"}
                    onChange={(e) =>
                      patchConfig({
                        companies_filter_config: {
                          ...filt,
                          recent_funding: e.target.value || "any",
                        },
                      })
                    }
                  >
                    <option value="any">Any</option>
                    <option value="last_3_months">Last 3 months</option>
                    <option value="last_6_months">Last 6 months</option>
                    <option value="last_12_months">Last 12 months</option>
                    {filt.recent_funding &&
                    !["any", "last_3_months", "last_6_months", "last_12_months"].includes(
                      filt.recent_funding,
                    ) ? (
                      <option value={filt.recent_funding}>{filt.recent_funding}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Skip if contacted within (days)
                  <input
                    type="number"
                    min={0}
                    value={filt.skip_contacted_within_days ?? ""}
                    onChange={(e) =>
                      patchConfig({
                        companies_filter_config: {
                          ...filt,
                          skip_contacted_within_days: e.target.value
                            ? Number(e.target.value)
                            : null,
                        },
                      })
                    }
                  />
                </label>
              </div>
              <div className="checks">
                <label>
                  <input
                    type="checkbox"
                    checked={filt.skip_customers}
                    onChange={(e) =>
                      patchConfig({
                        companies_filter_config: {
                          ...filt,
                          skip_customers: e.target.checked,
                        },
                      })
                    }
                  />
                  Skip existing customers
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={filt.skip_open_deals}
                    onChange={(e) =>
                      patchConfig({
                        companies_filter_config: {
                          ...filt,
                          skip_open_deals: e.target.checked,
                        },
                      })
                    }
                  />
                  Skip companies with open deals
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={filt.skip_has_owner}
                    onChange={(e) =>
                      patchConfig({
                        companies_filter_config: {
                          ...filt,
                          skip_has_owner: e.target.checked,
                        },
                      })
                    }
                  />
                  Skip companies that already have an owner
                </label>
              </div>
            </section>

            {/* Hiring signal */}
            <section className="card">
              <h2>Hiring signal</h2>
              <p className="hint">
                Open engineering roles. Listed on the HubSpot
                company note.
              </p>
              <Segmented
                value={hire.mode}
                options={[
                  { id: "required", label: "Required" },
                  { id: "boost", label: "Boost ranking" },
                  { id: "ignore", label: "Ignore" },
                ]}
                onChange={(mode) =>
                  patchConfig({ hiring_signal_config: { ...hire, mode } })
                }
              />
              <ChipField
                legend="Role categories"
                options={ROLE_CATEGORIES}
                selected={hire.role_categories}
                onToggle={(v) =>
                  patchConfig({
                    hiring_signal_config: {
                      ...hire,
                      role_categories: toggleIn(hire.role_categories, v),
                    },
                  })
                }
              />
              <ChipField
                legend="Seniorities"
                options={SENIORITIES}
                selected={hire.seniorities}
                onToggle={(v) =>
                  patchConfig({
                    hiring_signal_config: {
                      ...hire,
                      seniorities: toggleIn(hire.seniorities, v),
                    },
                  })
                }
              />
              <div className="fields">
                <label>
                  Min open eng roles
                  <input
                    type="number"
                    min={0}
                    value={hire.min_open_eng_roles ?? ""}
                    onChange={(e) =>
                      patchConfig({
                        hiring_signal_config: {
                          ...hire,
                          min_open_eng_roles: e.target.value ? Number(e.target.value) : null,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Posted within (days)
                  <input
                    type="number"
                    min={0}
                    value={hire.posted_within_days ?? ""}
                    onChange={(e) =>
                      patchConfig({
                        hiring_signal_config: {
                          ...hire,
                          posted_within_days: e.target.value ? Number(e.target.value) : null,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Open longer than (days)
                  <input
                    type="number"
                    min={0}
                    value={hire.open_longer_than_days ?? ""}
                    onChange={(e) =>
                      patchConfig({
                        hiring_signal_config: {
                          ...hire,
                          open_longer_than_days: e.target.value
                            ? Number(e.target.value)
                            : null,
                        },
                      })
                    }
                  />
                </label>
                <CsvField
                  label="Job keywords (comma-separated)"
                  values={hire.job_keywords}
                  placeholder="python, kubernetes"
                  onChange={(job_keywords) =>
                    patchConfig({
                      hiring_signal_config: { ...hire, job_keywords },
                    })
                  }
                />
                <CsvField
                  label="Job locations (comma-separated)"
                  values={hire.job_locations}
                  placeholder="United States, Remote"
                  onChange={(job_locations) =>
                    patchConfig({
                      hiring_signal_config: { ...hire, job_locations },
                    })
                  }
                />
              </div>
              <fieldset className="chips">
                <legend>Sources</legend>
                {JOB_SOURCES.map((src) => (
                  <button
                    key={src.id}
                    type="button"
                    className={hire.sources.includes(src.id) ? "chip on" : "chip"}
                    onClick={() =>
                      patchConfig({
                        hiring_signal_config: {
                          ...hire,
                          sources: toggleIn(hire.sources, src.id),
                        },
                      })
                    }
                  >
                    {src.label}
                  </button>
                ))}
              </fieldset>
            </section>

            {/* Decision makers */}
            <section className="card">
              <h2>Decision makers</h2>
              <p className="hint">
                The agent works down this list until it has enough contacts per company.
              </p>
              <div className="fields">
                <div className="wide">
                  <span className="lbl">Target personas, in priority order</span>
                  <ul className="personas">
                    {dm.personas.map((persona, index) => (
                      <li key={`${persona}-${index}`}>
                        <span className="idx">{index + 1}</span>
                        <span className="name">{persona}</span>
                        <button
                          type="button"
                          className="icon"
                          aria-label={`Move up ${persona}`}
                          disabled={index === 0}
                          onClick={() => movePersona(index, -1)}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="icon"
                          aria-label={`Move down ${persona}`}
                          disabled={index === dm.personas.length - 1}
                          onClick={() => movePersona(index, 1)}
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          className="icon"
                          aria-label={`Remove ${persona}`}
                          onClick={() =>
                            patchConfig({
                              decision_makers_config: {
                                ...dm,
                                personas: dm.personas.filter((_, i) => i !== index),
                              },
                            })
                          }
                        >
                          ✕
                        </button>
                      </li>
                    ))}
                  </ul>
                  <select
                    aria-label="Add persona"
                    value=""
                    onChange={(e) => {
                      const persona = e.target.value;
                      if (!persona || dm.personas.includes(persona)) return;
                      patchConfig({
                        decision_makers_config: {
                          ...dm,
                          personas: [...dm.personas, persona],
                        },
                      });
                    }}
                  >
                    <option value="">Add a persona…</option>
                    {PERSONA_CHOICES.filter((persona) => !dm.personas.includes(persona)).map(
                      (persona) => (
                        <option key={persona} value={persona}>
                          {persona}
                        </option>
                      ),
                    )}
                  </select>
                </div>
                <label>
                  Email requirement
                  <select
                    value={dm.email_requirement}
                    onChange={(e) =>
                      patchConfig({
                        decision_makers_config: {
                          ...dm,
                          email_requirement: e.target.value,
                        },
                      })
                    }
                  >
                    <option value="verified_only">Verified only</option>
                    <option value="verified_likely">Verified + likely</option>
                    <option value="any">Any</option>
                    {dm.email_requirement === "guessed_ok" ? (
                      <option value="guessed_ok">Guessed OK</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Phone enrichment
                  <select
                    value={dm.phone_enrichment}
                    onChange={(e) =>
                      patchConfig({
                        decision_makers_config: {
                          ...dm,
                          phone_enrichment: e.target.value,
                        },
                      })
                    }
                  >
                    <option value="none">Off</option>
                    <option value="top_persona_only">Top persona only</option>
                    <option value="all_contacts">All contacts</option>
                  </select>
                </label>
              </div>
              <div className="checks">
                <label>
                  <input
                    type="checkbox"
                    checked={dm.skip_when_no_email}
                    onChange={(e) =>
                      patchConfig({
                        decision_makers_config: {
                          ...dm,
                          skip_when_no_email: e.target.checked,
                        },
                      })
                    }
                  />
                  Skip a contact when no email is found, and try the next persona
                </label>
              </div>
            </section>

            {/* HubSpot output */}
            <section className="card">
              <h2>HubSpot output</h2>
              <p className="hint">What gets written when the run finishes.</p>
              <div className="fields">
                <label>
                  If company exists
                  <select
                    value={hs.if_company_exists}
                    onChange={(e) =>
                      patchConfig({
                        hubspot_output_config: {
                          ...hs,
                          if_company_exists: e.target.value,
                        },
                      })
                    }
                  >
                    <option value="add_job_note_only">Add job note only</option>
                    <option value="update">Update company</option>
                    <option value="skip">Skip</option>
                  </select>
                </label>
                <label>
                  If contact exists
                  <select
                    value={hs.if_contact_exists}
                    onChange={(e) =>
                      patchConfig({
                        hubspot_output_config: {
                          ...hs,
                          if_contact_exists: e.target.value,
                        },
                      })
                    }
                  >
                    <option value="skip">Skip</option>
                    <option value="update">Update</option>
                    <option value="add_note">Add note only</option>
                  </select>
                </label>
                <label>
                  Lifecycle stage
                  <select
                    value={hs.lifecycle_stage}
                    onChange={(e) =>
                      patchConfig({
                        hubspot_output_config: {
                          ...hs,
                          lifecycle_stage: e.target.value,
                        },
                      })
                    }
                  >
                    <option value="lead">Lead</option>
                    <option value="marketingqualifiedlead">Marketing qualified lead</option>
                    <option value="salesqualifiedlead">Sales qualified lead</option>
                    <option value="opportunity">Opportunity</option>
                    <option value="subscriber">Subscriber</option>
                    <option value="customer">Customer</option>
                    {hs.lifecycle_stage &&
                    ![
                      "lead",
                      "marketingqualifiedlead",
                      "salesqualifiedlead",
                      "opportunity",
                      "subscriber",
                      "customer",
                    ].includes(hs.lifecycle_stage) ? (
                      <option value={hs.lifecycle_stage}>{hs.lifecycle_stage}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Lead status
                  <select
                    value={hs.lead_status}
                    onChange={(e) =>
                      patchConfig({
                        hubspot_output_config: { ...hs, lead_status: e.target.value },
                      })
                    }
                  >
                    <option value="new">New</option>
                    <option value="open">Open</option>
                    <option value="ATTEMPTED_TO_CONTACT">Attempted to contact</option>
                    {hs.lead_status &&
                    !["new", "open", "ATTEMPTED_TO_CONTACT"].includes(hs.lead_status) ? (
                      <option value={hs.lead_status}>{hs.lead_status}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Add to list (optional id/name)
                  <input
                    value={hs.add_to_list || ""}
                    onChange={(e) =>
                      patchConfig({
                        hubspot_output_config: {
                          ...hs,
                          add_to_list: e.target.value || null,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Follow-up task (days)
                  <input
                    type="number"
                    min={0}
                    value={hs.follow_up_task_days ?? ""}
                    onChange={(e) =>
                      patchConfig({
                        hubspot_output_config: {
                          ...hs,
                          follow_up_task_days: e.target.value
                            ? Number(e.target.value)
                            : null,
                        },
                      })
                    }
                  />
                </label>
              </div>
            </section>

            {/* Email draft */}
            <section className="card">
              <h2>Email draft</h2>
              <p className="hint">
                One personalized draft per contact, built from the hiring signal and role.
              </p>
              <div className="fields">
                <label>
                  Offer
                  <select
                    value={email.offer}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: { ...email, offer: e.target.value },
                      })
                    }
                  >
                    <option value="staff_augmentation">Staff augmentation</option>
                    <option value="dedicated_team">Dedicated team</option>
                    <option value="project_delivery">Project delivery</option>
                    <option value="ai_data">AI / data services</option>
                  </select>
                </label>
                <label>
                  Angle
                  <select
                    value={email.angle}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: { ...email, angle: e.target.value },
                      })
                    }
                  >
                    <option value="hiring_signal">Hiring signal (“saw you're hiring…”)</option>
                    <option value="case_study">Relevant case study</option>
                    <option value="time_to_hire">Time-to-hire / cost</option>
                    <option value="stack_match">Tech-stack match</option>
                    {email.angle &&
                    !["hiring_signal", "case_study", "time_to_hire", "stack_match"].includes(
                      email.angle,
                    ) ? (
                      <option value={email.angle}>{email.angle}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Tone
                  <select
                    value={email.tone}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: { ...email, tone: e.target.value },
                      })
                    }
                  >
                    <option value="consultative">Consultative</option>
                    <option value="direct">Direct</option>
                    <option value="casual">Casual</option>
                    {email.tone &&
                    !["consultative", "direct", "casual"].includes(email.tone) ? (
                      <option value={email.tone}>{email.tone}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Length
                  <select
                    value={email.length}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: { ...email, length: e.target.value },
                      })
                    }
                  >
                    <option value="short">Short (under 90 words)</option>
                    <option value="medium">Medium (90–150 words)</option>
                    {email.length && !["short", "medium"].includes(email.length) ? (
                      <option value={email.length}>{email.length}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Call to action
                  <select
                    value={email.call_to_action}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: {
                          ...email,
                          call_to_action: e.target.value,
                        },
                      })
                    }
                  >
                    <option value="15_minute_call">15-minute call</option>
                    <option value="question">Reply to a question</option>
                    <option value="calendar">Calendar link</option>
                    {email.call_to_action &&
                    !["15_minute_call", "question", "calendar"].includes(email.call_to_action) ? (
                      <option value={email.call_to_action}>{email.call_to_action}</option>
                    ) : null}
                  </select>
                </label>
                <label>
                  Language
                  <select
                    value={email.language}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: { ...email, language: e.target.value },
                      })
                    }
                  >
                    <option value="en">English</option>
                    <option value="es">Spanish</option>
                  </select>
                </label>
                <label>
                  Drafts per contact
                  <input
                    type="number"
                    min={1}
                    max={3}
                    value={email.drafts_per_contact}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: {
                          ...email,
                          drafts_per_contact: Number(e.target.value) || 1,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  Save as
                  <select
                    value={email.save_as}
                    onChange={(e) =>
                      patchConfig({
                        email_draft_config: { ...email, save_as: e.target.value },
                      })
                    }
                  >
                    <option value="note">Contact note</option>
                    <option value="property">Contact property (ai_email_draft)</option>
                    <option value="task">Body of the follow-up task</option>
                    <option value="sequence">Enroll in HubSpot sequence</option>
                    {email.save_as &&
                    !["note", "property", "task", "sequence"].includes(email.save_as) ? (
                      <option value={email.save_as}>{email.save_as}</option>
                    ) : null}
                  </select>
                </label>
              </div>
              <label>
                Extra instructions
                <textarea
                  className="editor short"
                  value={email.extra_instructions}
                  maxLength={500}
                  onChange={(e) =>
                    patchConfig({
                      email_draft_config: {
                        ...email,
                        extra_instructions: e.target.value,
                      },
                    })
                  }
                  placeholder="Optional guidance for the outreach LLM (max 500 chars)"
                />
              </label>
            </section>

            {/* Run mode */}
            <section className="card">
              <h2>Run mode & notifications</h2>
              <p className="hint">
                Start new campaigns in review mode until the output looks right.
              </p>
              <div className="wide">
                <span className="lbl" id="run-mode-label">
                  Run mode
                </span>
                <div role="group" aria-labelledby="run-mode-label">
                  <Segmented
                    value={config.run_mode}
                    options={[
                      { id: "review", label: "Review first" },
                      { id: "live", label: "Live" },
                      { id: "dry_run", label: "Dry run" },
                    ]}
                    onChange={(run_mode) => patchConfig({ run_mode })}
                  />
                </div>
                <p className="hint">{RUN_MODE_HELP[config.run_mode]}</p>
              </div>
              <div className="checks">
                <span className="lbl">Email summary</span>
                <label>
                  <input
                    type="checkbox"
                    checked={config.email_owner !== false}
                    onChange={(e) => patchConfig({ email_owner: e.target.checked })}
                  />
                  Email the owner after each run
                </label>
              </div>
            </section>

            <p className="hint">
              Test run uses the fields above as a dry run. It does not save the campaign and does not
              write to HubSpot.
            </p>
            <div className="row">
              <button
                type="button"
                className="secondary"
                onClick={() => void onTestRun()}
                disabled={busy !== null || icps.length === 0}
              >
                {busy === "test" ? "Starting test…" : "Test run"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void saveCampaign("draft")}
                disabled={busy !== null || icps.length === 0}
              >
                {busy === "draft" ? "Saving…" : "Save as draft"}
              </button>
              <button type="submit" disabled={busy !== null || icps.length === 0}>
                {busy === "active"
                  ? "Saving…"
                  : editing
                    ? "Update campaign"
                    : "Create campaign"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setShowForm(false);
                  setEditing(null);
                }}
              >
                Cancel
              </button>
            </div>
          </form>

          <aside className="card each-run sticky">
            <h2>Each run</h2>
            <dl className="stats">
              <div>
                <dt>Companies</dt>
                <dd>{config.companies_per_run}</dd>
              </div>
              <div>
                <dt>Contacts</dt>
                <dd>{contactsPerRun}</dd>
              </div>
              <div>
                <dt>Est. credits / run</dt>
                <dd className={overCreditBudget ? "over-budget" : undefined}>{estCredits}</dd>
              </div>
              <div>
                <dt>Est. credits / month</dt>
                <dd>{estMonthly}</dd>
              </div>
            </dl>
            <p className="hint">
              Placeholder rates ({CREDIT_PER_CONTACT}/contact, {CREDIT_PER_PHONE}/phone). Set them to
              your Apollo plan. Monthly assumes ~weekly cadence.
            </p>
            {selectedIcp ? (
              <p className="hint">
                ICP: <strong>{selectedIcp.title}</strong>
                {selectedIcp.version ? ` · ${selectedIcp.version}` : ""}
              </p>
            ) : null}
          </aside>
        </div>
      ) : null}

      <section className="card">
        {campaigns.length === 0 ? (
          <p className="hint">{busy === "load" ? "Loading…" : "No campaigns yet."}</p>
        ) : (
          <ul className="list campaigns">
            {campaigns.map((c) => (
              <li key={c.campaign_id}>
                <div className="list-main">
                  <strong>{c.name}</strong>
                  <span>
                    {c.status}
                    {c.config.company_goal
                      ? ` · ${c.companies_upserted ?? 0}/${c.config.company_goal}`
                      : ""}{" "}
                    · {ownerLabel(c)} · {c.config.run_mode} · {c.config.companies_per_run}/run · ICP{" "}
                    {icpTitle(c.icp_id)}
                  </span>
                </div>
                <div className="row wrap">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => onOpenRuns(c.campaign_id)}
                  >
                    Runs & schedules
                  </button>
                  <button type="button" className="secondary" onClick={() => resetForm(c)}>
                    Edit
                  </button>
                  {c.status !== "active" ? (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setCampaignStatus(c, "active")}
                      disabled={busy !== null}
                    >
                      Activate
                    </button>
                  ) : null}
                  {c.status !== "ended" ? (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setCampaignStatus(c, "ended")}
                      disabled={busy !== null}
                    >
                      End
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="secondary danger"
                    onClick={() => onDelete(c.campaign_id)}
                    disabled={busy !== null}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
