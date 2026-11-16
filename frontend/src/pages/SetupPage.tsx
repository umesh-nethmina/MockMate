import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { listCvs, startSession, uploadCv, type CV, type Level, type Personality, type SessionType } from "../api";
import { useAuth } from "../auth";

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
const TYPES: { value: SessionType; label: string }[] = [
  { value: "full", label: "Full interview (HR, then technical)" },
  { value: "hr", label: "HR / behavioural only" },
  { value: "technical", label: "Technical only" },
];
const PERSONALITIES: { value: Personality; label: string; hint: string }[] = [
  { value: "friendly_hr", label: "Friendly HR", hint: "Warm and patient" },
  { value: "strict_tech_lead", label: "Strict tech lead", hint: "Pushes on vague claims" },
  { value: "fast_paced_founder", label: "Fast-paced founder", hint: "Short, punchy, impact-focused" },
];
const JD_MAX = 5000;
const CV_MAX_BYTES = 5 * 1024 * 1024;

export default function SetupPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [rolePick, setRolePick] = useState(ROLES[0]);
  const [customRole, setCustomRole] = useState("");
  const [level, setLevel] = useState<Level>("junior");
  const [jd, setJd] = useState("");
  const [sessionType, setSessionType] = useState<SessionType>("full");
  const [personality, setPersonality] = useState<Personality>("friendly_hr");
  const [cvs, setCvs] = useState<CV[]>([]);
  const [cvId, setCvId] = useState<number | null>(null);
  const [cvNote, setCvNote] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listCvs()
      .then((list) => {
        setCvs(list);
        if (list.length) setCvId(list[0].id);
      })
      .catch(() => setCvs([]));
  }, []);

  const role = rolePick === CUSTOM ? customRole.trim() : rolePick;

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setCvNote(null);
    if (file.size > CV_MAX_BYTES) {
      setCvNote("That file is larger than 5 MB.");
      return;
    }
    setUploading(true);
    try {
      const cv = await uploadCv(file);
      setCvs((list) => [cv, ...list]);
      setCvId(cv.id);
      setCvNote(
        cv.truncated
          ? "CV uploaded. It is long, so only the first part will be used."
          : "CV uploaded. The PDF itself is not stored, only its text.",
      );
    } catch (err) {
      setCvNote((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (role.length < 2) {
      setError("Please enter a role.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const turn = await startSession({
        role,
        level,
        job_description: jd.trim(),
        session_type: sessionType,
        personality,
        cv_id: cvId,
      });
      navigate(`/interview/${turn.session_id}`);
    } catch (err) {
      setError((err as Error).message); // setup data stays in the form so the user can retry (UC-01 3a)
      setBusy(false);
    }
  }

  return (
    <>
      <section className="hero">
        <h1>Set up your interview</h1>
        {user?.is_guest && (
          <p className="notice">
            You're trying MockMate as a guest: one 5-question interview. Create an account to save your history.
          </p>
        )}
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
            rows={6}
            maxLength={JD_MAX}
            placeholder="Paste the job advert so questions match the role."
            value={jd}
            onChange={(e) => setJd(e.target.value)}
          />
          <small className="muted counter">
            {jd.length.toLocaleString()} / {JD_MAX.toLocaleString()}
          </small>
        </div>

        <div className="field">
          <label htmlFor="cv">
            CV <span className="muted">(optional, PDF up to 5 MB)</span>
          </label>
          <div className="row">
            <select
              id="cv"
              value={cvId ?? ""}
              onChange={(e) => setCvId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">No CV</option>
              {cvs.map((cv) => (
                <option key={cv.id} value={cv.id}>
                  {cv.file_name}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? "Reading PDF…" : "Upload PDF"}
            </button>
            <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={onFile} />
          </div>
          {cvNote && (
            <small className="muted" role="status">
              {cvNote}
            </small>
          )}
          <small className="muted">With a CV, you'll be asked about one of your projects.</small>
        </div>

        <div className="two-col">
          <div className="field">
            <label htmlFor="type">Interview type</label>
            <select id="type" value={sessionType} onChange={(e) => setSessionType(e.target.value as SessionType)}>
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="personality">Interviewer style</label>
            <select
              id="personality"
              value={personality}
              onChange={(e) => setPersonality(e.target.value as Personality)}
            >
              {PERSONALITIES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label} - {p.hint}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button className="primary" type="submit" disabled={busy || uploading}>
          {busy ? "Preparing your first question…" : "Start interview"}
        </button>
        <p className="muted small">
          {user?.is_guest ? "5" : "8"} questions · about {user?.is_guest ? "10" : "15"} minutes · text answers
        </p>
      </form>
    </>
  );
}
