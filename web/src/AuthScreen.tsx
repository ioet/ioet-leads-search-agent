import { FormEvent, useMemo, useState } from "react";
import { login, signup, verifyEmail } from "./api";

type Mode = "login" | "signup" | "verify";

type Props = {
  onAuthenticated: () => void;
  initialMode?: Mode;
  initialToken?: string;
};

export default function AuthScreen({
  onAuthenticated,
  initialMode = "login",
  initialToken = "",
}: Props) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(initialToken);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string }>();

  const title = useMemo(() => {
    if (mode === "signup") return "Create account";
    if (mode === "verify") return "Verify email";
    return "Sign in";
  }, [mode]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(undefined);
    try {
      if (mode === "signup") {
        const result = await signup(email.trim(), password);
        setMessage({ kind: "ok", text: result.message });
        setMode("verify");
      } else if (mode === "verify") {
        const result = await verifyEmail(token.trim());
        setMessage({ kind: "ok", text: result.message });
        setMode("login");
      } else {
        await login(email.trim(), password);
        onAuthenticated();
      }
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell auth-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Leads Search Agent</p>
          <h1>{title}</h1>
          <p>@ioet.com accounts only. Sessions use httpOnly cookies.</p>
        </div>
      </header>

      {message ? <div className={`banner ${message.kind}`}>{message.text}</div> : null}

      <form className="card" onSubmit={onSubmit}>
        {mode !== "verify" ? (
          <>
            <label>
              Email
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                placeholder="you@ioet.com"
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </label>
          </>
        ) : (
          <label>
            Verification token
            <input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
              placeholder="Paste token from email / logs"
            />
          </label>
        )}
        <div className="row">
          <button type="submit" disabled={busy}>
            {busy ? "Working…" : title}
          </button>
        </div>
      </form>

      <nav className="auth-links">
        {mode !== "login" ? (
          <button type="button" className="linkish" onClick={() => setMode("login")}>
            Sign in
          </button>
        ) : null}
        {mode !== "signup" ? (
          <button type="button" className="linkish" onClick={() => setMode("signup")}>
            Create account
          </button>
        ) : null}
        {mode !== "verify" ? (
          <button type="button" className="linkish" onClick={() => setMode("verify")}>
            Verify email
          </button>
        ) : null}
      </nav>
    </main>
  );
}
