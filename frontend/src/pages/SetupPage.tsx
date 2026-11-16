import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { startSession, type Level } from "../api";

const ROLES = [
  "Python developer",
  "Backend developer",
  "Frontend developer",
  "Full-stack developer",
  "Data analyst",
  "QA engineer",
];
const CUSTOM = "__custom__";
const LEVELS: { value: Level; label: string; hint: string }[] = [
  { value: "intern", label: "Intern", hint: "Fundamentals and learning ability" },
  { value: "junior", label: "Junior", hint: "Fundamentals plus applied practice" },
  { value: "mid", label: "Mid", hint: "Design trade-offs and ownership" },
];
const JD_MAX = 5000;

export default function SetupPage() {
  const navigate = useNavigate();
  const [rolePick, setRolePick] = useState(ROLES[0]);
  const [customRole, setCustomRole] = useState("");
  const [level, setLevel] = useState<Level>("junior");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const role = rolePick === CUSTOM ? customRole.trim() : rolePick;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (role.length < 2) {
      setError("Please enter a role.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const turn = await startSession({ role, level, job_description: jd.trim() });
      navigate(`/interview/${turn.session_id}`);
    } catch (err) {
      setError((err as Error).message); // setup data stays in the form so the user can retry (UC-01 3a)
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <h1>Practise your next interview</h1>
        <p className="muted">
          An AI interviewer asks one question at a time, follows up on vague answers, and gives you a
          scored report with model answers at the end.
        </p>
      </section>

      <form className="card form" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="role">Target role</label>
          <select id="role" value={rolePick} onChange={(e) => setRolePick(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
            <option value={CUSTOM}>Other (type your own)</option>
          </select>
          {rolePick === CUSTOM && (
            <input
              aria-label="Custom role"
              placeholder="e.g. DevOps engineer"
              maxLength={100}
              value={customRole}
              onChange={(e) => setCustomRole(e.target.value)}
              autoFocus
            />
          )}
        </div>

        <fieldset className="field">
          <legend>Level</legend>
          <div className="segmented">
            {LEVELS.map((l) => (
              <label key={l.value} className={level === l.value ? "selected" : ""}>
                <input
                  type="radio"
                  name="level"
                  value={l.value}
                  checked={level === l.value}
                  onChange={() => setLevel(l.value)}
                />
                <span>{l.label}</span>
                <small className="muted">{l.hint}</small>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="jd">
            Job description <span className="muted">(optional, recommended)</span>
          </label>
          <textarea
            id="jd"
            rows={7}
            maxLength={JD_MAX}
            placeholder="Paste the job advert so questions match the role."
            value={jd}
            onChange={(e) => setJd(e.target.value)}
          />
          <small className="muted counter">
            {jd.length.toLocaleString()} / {JD_MAX.toLocaleString()}
          </small>
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Preparing your first question…" : "Start interview"}
        </button>
        <p className="muted small">8 questions · about 15 minutes · text answers</p>
      </form>
    </>
  );
}
