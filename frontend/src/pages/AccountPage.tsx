import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deleteAccount, deleteCv, downloadFile, listCvs, type CV } from "../api";
import { useAuth } from "../auth";

export default function AccountPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [cvs, setCvs] = useState<CV[]>([]);
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCvs()
      .then(setCvs)
      .catch(() => setCvs([]));
  }, []);

  if (!user) return null;

  async function removeCv(cv: CV) {
    if (!window.confirm(`Delete ${cv.file_name}?`)) return;
    try {
      await deleteCv(cv.id);
      setCvs((list) => list.filter((c) => c.id !== cv.id));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function onDelete(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      logout();
      navigate("/login", { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <h1>{user.is_guest ? "Guest session" : "Account"}</h1>

      <section className="card">
        {user.is_guest ? (
          <p>
            You're using MockMate as a guest. Your interview is deleted automatically after 24 hours.{" "}
            <Link to="/login">Create an account</Link> to keep your history.
          </p>
        ) : (
          <dl className="details">
            <dt>Name</dt>
            <dd>{user.name || "-"}</dd>
            <dt>Email</dt>
            <dd>{user.email}</dd>
          </dl>
        )}
      </section>

      <section className="card">
        <h2 className="h3">Your CVs</h2>
        {cvs.length === 0 ? (
          <p className="muted">No CVs uploaded. Only the extracted text of a CV is stored, never the PDF.</p>
        ) : (
          <ul className="plain">
            {cvs.map((cv) => (
              <li key={cv.id} className="row spread">
                <span>
                  {cv.file_name}{" "}
                  <span className="muted small">{new Date(cv.uploaded_at).toLocaleDateString()}</span>
                </span>
                <button className="ghost small" onClick={() => void removeCv(cv)}>
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card row spread">
        <span>
          <strong>Download your data</strong>
          <br />
          <span className="muted small">
            Everything MockMate stores about you (account, CV text, interviews, scores, reports) as one JSON file.
          </span>
        </span>
        <button
          type="button"
          onClick={() => {
            setError(null);
            downloadFile("/users/me/export", "mockmate-data.json").catch((e: Error) => setError(e.message));
          }}
        >
          Export my data
        </button>
      </section>

      <section className="card danger">
        <h2 className="h3">Delete {user.is_guest ? "guest data" : "account"}</h2>
        <p>
          This permanently deletes {user.is_guest ? "your guest interview" : "your account, CVs, interviews and reports"}.
          It cannot be undone.
        </p>
        {!confirming ? (
          <button className="danger-button" onClick={() => setConfirming(true)}>
            Delete {user.is_guest ? "my data" : "my account"}…
          </button>
        ) : (
          <form className="form" onSubmit={onDelete}>
            {!user.is_guest && (
              <div className="field">
                <label htmlFor="confirm-password">Confirm with your password</label>
                <input
                  id="confirm-password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoFocus
                />
              </div>
            )}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <div className="row">
              <button type="submit" className="danger-button" disabled={busy}>
                {busy ? "Deleting…" : "Delete permanently"}
              </button>
              <button type="button" className="ghost" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>
    </>
  );
}
