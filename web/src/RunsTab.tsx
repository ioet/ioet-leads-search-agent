import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  CampaignPublic,
  CampaignRunPublic,
  createRun,
  createSchedule,
  deleteSchedule,
  listCampaigns,
  listRuns,
  listSchedules,
  SchedulePublic,
  updateSchedule,
} from "./api";

type Props = {
  onMessage: (msg: { kind: "ok" | "error" | "warn"; text: string } | undefined) => void;
  initialCampaignId?: string;
};

export default function RunsTab({ onMessage, initialCampaignId }: Props) {
  const [campaigns, setCampaigns] = useState<CampaignPublic[]>([]);
  const [campaignId, setCampaignId] = useState(initialCampaignId || "");
  const [runs, setRuns] = useState<CampaignRunPublic[]>([]);
  const [schedules, setSchedules] = useState<SchedulePublic[]>([]);
  const [busy, setBusy] = useState<string | null>("load");

  const [schedType, setSchedType] = useState<"once" | "recurring">("recurring");
  const [expression, setExpression] = useState("0 7 * * 1");
  const [timezone, setTimezone] = useState("UTC");

  useEffect(() => {
    if (initialCampaignId) setCampaignId(initialCampaignId);
  }, [initialCampaignId]);

  const refreshCampaigns = useCallback(async () => {
    const rows = await listCampaigns();
    setCampaigns(rows);
    if (!campaignId && rows[0]) setCampaignId(rows[0].campaign_id);
  }, [campaignId]);

  const refreshDetail = useCallback(async (id: string) => {
    if (!id) {
      setRuns([]);
      setSchedules([]);
      return;
    }
    const [r, s] = await Promise.all([listRuns(id), listSchedules(id)]);
    setRuns(r);
    setSchedules(s);
  }, []);

  useEffect(() => {
    setBusy("load");
    refreshCampaigns()
      .catch((err: Error) => onMessage({ kind: "error", text: err.message }))
      .finally(() => setBusy(null));
  }, [refreshCampaigns, onMessage]);

  useEffect(() => {
    if (!campaignId) return;
    setBusy("detail");
    refreshDetail(campaignId)
      .catch((err: Error) => onMessage({ kind: "error", text: err.message }))
      .finally(() => setBusy(null));
  }, [campaignId, refreshDetail, onMessage]);

  const hasOpenRun = runs.some((run) => run.status === "running" || run.status === "pending");

  useEffect(() => {
    if (!campaignId || !hasOpenRun) return;
    const timer = window.setInterval(() => {
      refreshDetail(campaignId).catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [campaignId, hasOpenRun, refreshDetail]);

  async function onRunNow() {
    if (!campaignId) return;
    setBusy("run");
    onMessage(undefined);
    try {
      const run = await createRun(campaignId, "manual");
      await refreshDetail(campaignId);
      onMessage({
        kind: "ok",
        text: `Started run ${run.run_id.slice(0, 8)}… (${run.status})`,
      });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onAddSchedule(event: FormEvent) {
    event.preventDefault();
    if (!campaignId || !expression.trim()) return;
    setBusy("schedule");
    onMessage(undefined);
    try {
      await createSchedule(campaignId, {
        type: schedType,
        expression: expression.trim(),
        timezone: timezone.trim() || "UTC",
        enabled: true,
      });
      await refreshDetail(campaignId);
      onMessage({ kind: "ok", text: "Schedule created and synced to LittleHorse." });
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function toggleSchedule(schedule: SchedulePublic) {
    setBusy("toggle");
    try {
      await updateSchedule(schedule.schedule_id, { enabled: !schedule.enabled });
      await refreshDetail(campaignId);
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  async function onDeleteSchedule(scheduleId: string) {
    if (!window.confirm("Delete this schedule?")) return;
    setBusy("delete");
    try {
      await deleteSchedule(scheduleId);
      await refreshDetail(campaignId);
    } catch (err) {
      onMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  }

  const selected = campaigns.find((c) => c.campaign_id === campaignId);

  return (
    <div className="stack">
      <section className="card">
        <h2>Campaign</h2>
        <div className="fields">
          <label>
            Select campaign
            <select
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
            >
              {campaigns.length === 0 ? <option value="">No campaigns</option> : null}
              {campaigns.map((c) => (
                <option key={c.campaign_id} value={c.campaign_id}>
                  {c.name} ({c.status})
                </option>
              ))}
            </select>
          </label>
        </div>
        {selected ? (
          <p className="hint">
            {selected.config.run_mode} · {selected.config.companies_per_run} companies/run
          </p>
        ) : null}
        <div className="row">
          <button
            type="button"
            onClick={onRunNow}
            disabled={!campaignId || selected?.status !== "active" || busy !== null}
          >
            {busy === "run" ? "Starting…" : "Run now"}
          </button>
          {selected && selected.status !== "active" ? (
            <span className="hint">Activate the campaign to run.</span>
          ) : null}
        </div>
      </section>

      <section className="card">
        <h2>Schedules</h2>
        <form className="stack tight" onSubmit={onAddSchedule}>
          <div className="fields">
            <label>
              Type
              <select
                value={schedType}
                onChange={(e) => {
                  const next = e.target.value as "once" | "recurring";
                  setSchedType(next);
                  setExpression(next === "once" ? "2026-12-01T15:00:00Z" : "0 7 * * 1");
                }}
              >
                <option value="recurring">recurring (cron)</option>
                <option value="once">once (ISO datetime)</option>
              </select>
            </label>
            <label>
              Expression
              <input
                value={expression}
                onChange={(e) => setExpression(e.target.value)}
                placeholder={schedType === "once" ? "2026-12-01T15:00:00Z" : "0 7 * * 1"}
                required
              />
            </label>
            <label>
              Timezone
              <input value={timezone} onChange={(e) => setTimezone(e.target.value)} />
            </label>
          </div>
          <p className="hint">
            Recurring cron is treated as UTC. Once datetimes are converted to UTC for LittleHorse.
          </p>
          <div className="row">
            <button type="submit" disabled={!campaignId || busy !== null}>
              {busy === "schedule" ? "Creating…" : "Add schedule"}
            </button>
          </div>
        </form>

        {schedules.length === 0 ? (
          <p className="hint">No schedules for this campaign.</p>
        ) : (
          <ul className="list">
            {schedules.map((s) => (
              <li key={s.schedule_id}>
                <div className="list-main">
                  <strong>
                    {s.type} · {s.expression}
                  </strong>
                  <span>
                    {s.timezone} · {s.enabled ? "enabled" : "disabled"}
                    {s.lh_schedule_id ? ` · LH ${s.lh_schedule_id}` : ""}
                  </span>
                </div>
                <div className="row wrap">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => toggleSchedule(s)}
                    disabled={busy !== null}
                  >
                    {s.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    type="button"
                    className="secondary danger"
                    onClick={() => onDeleteSchedule(s.schedule_id)}
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

      <section className="card">
        <h2>Runs</h2>
        {runs.length === 0 ? (
          <p className="hint">{busy === "detail" || busy === "load" ? "Loading…" : "No runs yet."}</p>
        ) : (
          <ul className="list">
            {runs.map((run) => (
              <li key={run.run_id}>
                <div className="list-main">
                  <strong>
                    {run.status} · {run.trigger}
                  </strong>
                  <span>
                    {run.started_at || run.created_at}
                    {run.lh_wf_run_id ? ` · ${run.lh_wf_run_id}` : ""}
                  </span>
                  {run.result_summary ? (
                    <span className="error-line">
                      {typeof run.result_summary.error === "string"
                        ? run.result_summary.error
                        : typeof run.result_summary.step === "string"
                          ? `${run.result_summary.step} failed`
                          : null}
                    </span>
                  ) : null}
                  {run.result_summary ? (
                    <pre className="mini">{JSON.stringify(run.result_summary, null, 2)}</pre>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
