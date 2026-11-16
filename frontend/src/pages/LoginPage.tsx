import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";

export default function LoginPage() {
  const { user, login, register, guest } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next")?.startsWith("/") ? params.get("next")! : "/";
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to={next} replace />;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      navigate(next, { replace: true });
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void run(() => (mode === "login" ? login(email, password) : register(email, password, name)));
  }

  return (
    <div className="auth">
      <section className="hero">
        <h1>Practise your next interview</h1>
        <p className="muted">
          An AI interviewer asks one question at a time, follows up on vague answers, and gives you a scored report
          with model answers.
        </p>
      </section>

      <div className="card">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={mode === "login"} onClick={() => setMode("login")}>
            Log in
          </button>
          <button role="tab" aria-selected={mode === "register"} onClick={() => setMode("register")}>
            Create account
          </button>
        </div>

        <form className="form" onSubmit={onSubmit}>
          {mode === "register" && (
            <div className="field">
              <label htmlFor="name">Name</label>
              <input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode === "register" && (
              <small className="muted">At least 8 characters, mixing letters with numbers or symbols.</small>
            )}
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" type="submit" disabled={busy}>
            {mode === "login" ? "Log in" : "Create account"}
          </button>
        </form>

        <div className="divider">
          <span>or</span>
        </div>
        <button className="wide" onClick={() => void run(guest)} disabled={busy}>
          Try as a guest
        </button>
        <p className="muted small center">One short text interview. Guest data is deleted after 24 hours.</p>
      </div>
    </div>
  );
}
