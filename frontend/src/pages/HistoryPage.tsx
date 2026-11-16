import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteSession, mySessions, type SessionSummary } from "../api";

const TYPE_LABEL: Record<string, string> = { full: "Full", hr: "HR", technical: "Technical" };

export default function HistoryPage() {
  const [rows, setRows] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mySessions()
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function remove(s: SessionSummary) {
    if (!window.confirm(`Delete the ${s.role} interview from ${new Date(s.started_at).toLocaleDateString()}?`)) return;
    try {
      await deleteSession(s.id);
      setRows((list) => list?.filter((r) => r.id !== s.id) ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!rows) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1>My interviews</h1>
      {rows.length === 0 ? (
        <p className="card">
          No interviews yet. <Link to="/">Start your first one</Link>.
        </p>
      ) : (
        <ul className="history">
          {rows.map((s) => {
            const href = s.overall_score !== null ? `/report/${s.id}` : `/interview/${s.id}`;
            return (
              <li key={s.id} className="card history-row">
                <Link to={href} className="history-main">
                  <strong>{s.role}</strong>
                  <span className="muted small">
                    {new Date(s.started_at).toLocaleString()} · {s.level} · {TYPE_LABEL[s.session_type] ?? s.session_type}
                  </span>
                </Link>
                <span className="history-score">
                  {s.overall_score !== null ? (
                    <>
                      <strong>{s.overall_score.toFixed(1)}</strong>
                      <span className="muted">/10</span>
                    </>
                  ) : (
                    <span className="muted small">
                      {s.status === "active" ? `In progress (${s.questions_asked}/${s.question_limit})` : "No report"}
                    </span>
                  )}
                </span>
                <button className="ghost small" onClick={() => void remove(s)} aria-label={`Delete ${s.role} interview`}>
                  Delete
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
