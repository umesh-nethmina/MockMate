import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { endSession, getSession, sendAnswer, type Message, type SessionState } from "../api";

export default function InterviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionState | null>(null);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Reload state from the server, so a refresh never loses progress (NFR-12)
  useEffect(() => {
    getSession(id)
      .then((s) => {
        if (s.has_report) navigate(`/report/${id}`, { replace: true });
        else setSession(s);
      })
      .catch((e: Error) => setError(e.message));
  }, [id, navigate]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [session?.messages.length, thinking]);

  const finish = useCallback(async () => {
    setFinishing(true);
    setError(null);
    try {
      await endSession(id);
      navigate(`/report/${id}`);
    } catch (e) {
      setError((e as Error).message);
      setFinishing(false);
    }
  }, [id, navigate]);

  // Ended (question limit reached or closed earlier) but no report yet, e.g. after a refresh
  const ended =
    session !== null &&
    (session.status === "completed" || session.messages[session.messages.length - 1]?.kind === "closing");
  useEffect(() => {
    if (ended && !finishing && !error) void finish();
  }, [ended, finishing, error, finish]);

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || !session || thinking) return;

    const optimistic: Message = {
      id: -Date.now(),
      speaker: "candidate",
      kind: "answer",
      round: "",
      topic: null,
      text,
      created_at: new Date().toISOString(),
    };
    setSession({ ...session, messages: [...session.messages, optimistic] });
    setDraft("");
    setThinking(true);
    setError(null);
    try {
      await sendAnswer(id, text);
      setSession(await getSession(id)); // authoritative transcript; the effect above handles the end
    } catch (err) {
      // Nothing was saved server-side: restore the answer so the user can resend it
      setSession(session);
      setDraft(text);
      setError((err as Error).message);
    } finally {
      setThinking(false);
      inputRef.current?.focus();
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void submit();
  }

  function confirmEnd() {
    if (window.confirm("End the interview now and see your report?")) void finish();
  }

  if (!session) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted">Loading interview…</p>
    );
  }

  const current = Math.min(session.questions_asked, session.question_limit);
  const active = !ended && !finishing;

  return (
    <div className="interview">
      <div className="interview-head">
        <div>
          <h1 className="h2">{session.role}</h1>
          <p className="muted small">{session.level} level</p>
        </div>
        <div className="progress-wrap" aria-label={`Question ${current} of ${session.question_limit}`}>
          <span className="small">
            Question {current} of {session.question_limit}
          </span>
          <div className="progress">
            <div style={{ width: `${(current / session.question_limit) * 100}%` }} />
          </div>
        </div>
        <button className="ghost" onClick={confirmEnd} disabled={!active || thinking}>
          End interview
        </button>
      </div>

      <ol className="chat" aria-live="polite">
        {session.messages.map((m) => (
          <li key={m.id} className={`bubble ${m.speaker}`}>
            <span className="who">{m.speaker === "interviewer" ? "Interviewer" : "You"}</span>
            <p>{m.text}</p>
          </li>
        ))}
        {thinking && (
          <li className="bubble interviewer typing">
            <span className="who">Interviewer</span>
            <p>Thinking…</p>
          </li>
        )}
      </ol>
      <div ref={endRef} />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {finishing ? (
        <p className="card center">Scoring your answers and writing your report…</p>
      ) : ended ? (
        <button className="primary" onClick={() => void finish()}>
          Generate report
        </button>
      ) : (
        <form className="composer" onSubmit={submit}>
          <label htmlFor="answer" className="sr-only">
            Your answer
          </label>
          <textarea
            id="answer"
            ref={inputRef}
            rows={4}
            maxLength={5000}
            placeholder="Type your answer… (Ctrl+Enter to send)"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={thinking}
            autoFocus
          />
          <button className="primary" type="submit" disabled={thinking || !draft.trim()}>
            Send
          </button>
        </form>
      )}
    </div>
  );
}
