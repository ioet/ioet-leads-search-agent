import { useCallback, useEffect, useState } from "react";
import { logout, me, refreshSession, UserPublic } from "./api";
import AuthScreen from "./AuthScreen";
import CampaignsTab from "./CampaignsTab";
import IcpTab from "./IcpTab";
import RunsTab from "./RunsTab";
import "./App.css";

type Tab = "icps" | "campaigns" | "runs";

function verifyTokenFromUrl(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("token") || "";
}

export default function App() {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [booting, setBooting] = useState(true);
  const [tab, setTab] = useState<Tab>("campaigns");
  const [runsCampaignId, setRunsCampaignId] = useState<string>();
  const [message, setMessage] = useState<{ kind: "ok" | "error" | "warn"; text: string }>();

  const bootstrap = useCallback(async () => {
    try {
      setUser(await me());
    } catch {
      try {
        setUser(await refreshSession());
      } catch {
        setUser(null);
      }
    }
  }, []);

  useEffect(() => {
    bootstrap().finally(() => setBooting(false));
  }, [bootstrap]);

  const onMessage = useCallback(
    (msg: { kind: "ok" | "error" | "warn"; text: string } | undefined) => {
      setMessage(msg);
    },
    [],
  );

  async function onLogout() {
    try {
      await logout();
    } finally {
      setUser(null);
    }
  }

  if (booting) {
    return (
      <main className="shell">
        <p className="hint">Loading…</p>
      </main>
    );
  }

  if (!user) {
    const token = verifyTokenFromUrl();
    return (
      <AuthScreen
        onAuthenticated={() => {
          setBooting(true);
          bootstrap().finally(() => setBooting(false));
        }}
        initialMode={token ? "verify" : "login"}
        initialToken={token}
      />
    );
  }

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Leads Search Agent</p>
          <h1>Campaign builder</h1>
          <p>ICPs, campaigns, schedules, and runs.</p>
        </div>
        <div className="user-meta">
          <p className="meta">{user.email}</p>
          <button type="button" className="secondary" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="tabs">
        {(
          [
            ["icps", "ICP admin"],
            ["campaigns", "Campaigns"],
            ["runs", "Runs"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? "tab on" : "tab"}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {message ? <div className={`banner ${message.kind}`}>{message.text}</div> : null}

      {tab === "icps" ? <IcpTab onMessage={onMessage} /> : null}
      {tab === "campaigns" ? (
        <CampaignsTab
          currentUser={user}
          onMessage={onMessage}
          onOpenRuns={(campaignId) => {
            setRunsCampaignId(campaignId);
            setTab("runs");
          }}
        />
      ) : null}
      {tab === "runs" ? (
        <RunsTab onMessage={onMessage} initialCampaignId={runsCampaignId} />
      ) : null}
    </main>
  );
}
