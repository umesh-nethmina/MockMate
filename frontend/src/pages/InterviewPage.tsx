import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { endSession, getSession, sendAnswer, type Message, type SessionState } from "../api";
import { readPref, useSpeechRecognition, useSpeechSynthesis, writePref } from "../speech";

// The editor bundle is large, so it only loads for coding interviews
const CodingWorkspace = lazy(() => import("./CodingWorkspace"));

type Mode = "text" | "voice";

const PANELISTS = { friendly_hr: "Priya · HR", strict_tech_lead: "Marcus · Tech lead", fast_paced_founder: "Sam · Founder" };

const join = (a: string, b: string) => [a.trim(), b.trim()].filter(Boolean).join(" ");

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

  // ---- voice (FR-20..FR-23) ----
  const rec = useSpeechRecognition();
  const tts = useSpeechSynthesis();
  const [mode, setMode] = useState<Mode>(() => (rec.supported ? readPref<Mode>("mode", "text") : "text"));
  const [muted, setMuted] = useState(() => readPref<string>("muted", "false") === "true");
  const baseRef = useRef(""); // text already in the box when the mic was switched on
  const spokenRef = useRef<number | null>(null);

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

  // Dictated words flow into the answer box
  useEffect(() => {
    if (rec.listening) setDraft(join(baseRef.current, rec.transcript));
  }, [rec.transcript, rec.listening]);

  // Read each new interviewer message aloud unless muted (FR-21)
  const reload = useCallback(async () => setSession(await getSession(id)), [id]);

  // The coding workspace needs a wider page than the chat layout
  const wide = session?.session_type === "coding";
  useEffect(() => {
    document.body.classList.toggle("wide-page", wide);
    return () => document.body.classList.remove("wide-page");
  }, [wide]);
  const interviewerMsgs = session?.messages.filter((m) => m.speaker === "interviewer") ?? [];
  const lastInterviewer = interviewerMsgs[interviewerMsgs.length - 1];

  // Microphone blocked or recognition failing: fall back to text (UC-01 4a), keeping whatever was dictated
  useEffect(() => {
    if (rec.error && mode === "voice") setMode("text");
  }, [rec.error, mode]);
  useEffect(() => {
    if (!lastInterviewer || spokenRef.current === lastInterviewer.id) return;
    spokenRef.current = lastInterviewer.id;
    if (!muted && !rec.listening) tts.speak(lastInterviewer.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- speak once per new message
  }, [lastInterviewer?.id]);

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

  function chooseMode(next: Mode) {
    if (next === mode) return;
    if (rec.listening) rec.stop();
    setMode(next);
    writePref("mode", next);
    if (next === "text") inputRef.current?.focus();
  }

  function toggleMute() {
    const next = !muted;
    setMuted(next);
    writePref("muted", String(next));
    if (next) tts.cancel();
  }

  function toggleMic() {
    if (rec.listening) {
      rec.stop();
      inputRef.current?.focus(); // review and edit the transcript before sending (FR-23)
    } else {
      tts.cancel(); // don't let the speakers talk into the microphone
      baseRef.current = draft;
      rec.start();
    }
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || !session || thinking) return;
    if (rec.listening) rec.stop();

    const raw = rec.peek();
    const voice = raw.transcript.trim() ? raw : undefined;
    const optimistic: Message = {
      id: -Date.now(),
      speaker: "candidate",
      kind: "answer",
      round: "",
      topic: null,
      persona: null,
      text,
      created_at: new Date().toISOString(),
    };
    setSession({ ...session, messages: [...session.messages, optimistic] });
    setDraft("");
    setThinking(true);
    setError(null);
    try {
      await sendAnswer(id, text, voice);
      rec.reset();
      setSession(await getSession(id)); // authoritative transcript; the effect above handles the end
    } catch (err) {
      // Nothing was saved server-side: restore the answer (and keep the voice data) so it can be resent
      setSession(session);
      setDraft(text);
      setError((err as Error).message);
    } finally {
      setThinking(false);
      if (mode === "text") inputRef.current?.focus();
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void submit();
  }

  function confirmEnd() {
    if (window.confirm("End the interview now and see your report?")) {
      rec.stop();
      tts.cancel();
      void finish();
    }
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
  const isCoding = session.session_type === "coding";
  const codeSubmitted = session.messages.some((m) => m.kind === "code");
  const roundLabel = isCoding ? "Coding round" : lastInterviewer?.round === "hr" ? "HR round" : "Technical round";
  const shown = rec.listening ? join(draft, rec.interim) : draft;

  return (
    <div className="interview">
      <div className="interview-head">
        <div>
          <h1 className="h2">{session.role}</h1>
          <p className="muted small">
            {session.level} level · {roundLabel}
          </p>
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

      {isCoding && (
        <Suspense fallback={<p className="muted">Loading the code editor…</p>}>
          <CodingWorkspace sessionId={id} active={active} onChanged={reload} />
        </Suspense>
      )}

      <ol className="chat" aria-live="polite">
        {session.messages.map((m) => (
          <li key={m.id} className={`bubble ${m.speaker} ${m.kind === "hint" ? "hint" : ""}`}>
            <span className="who">
              {m.speaker === "interviewer" ? (m.persona && session.panel ? PANELISTS[m.persona] : "Interviewer") : "You"}
              {m.speaker === "interviewer" && tts.supported && (
                <button
                  type="button"
                  className="replay"
                  onClick={() => tts.speak(m.text)}
                  aria-label="Read this question aloud"
                  title="Read aloud"
                >
                  🔊
                </button>
              )}
            </span>
            {m.kind === "code" ? <pre className="code">{m.text}</pre> : <p>{m.text}</p>}
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
      ) : isCoding && !codeSubmitted ? (
        <p className="muted small center">Submit your code to answer the interviewer's follow-up question.</p>
      ) : (
        <form className="composer" onSubmit={submit}>
          <div className="composer-bar">
            <div className="segmented-mini" role="group" aria-label="Answer mode">
              <button
                type="button"
                aria-pressed={mode === "text"}
                onClick={() => chooseMode("text")}
              >
                ⌨ Text
              </button>
              <button
                type="button"
                aria-pressed={mode === "voice"}
                onClick={() => chooseMode("voice")}
                disabled={!rec.supported}
                title={rec.supported ? undefined : "Voice answers need Chrome or Edge"}
              >
                🎤 Voice
              </button>
            </div>
            {tts.supported && (
              <button type="button" className="ghost small" onClick={toggleMute} aria-pressed={muted}>
                {muted ? "🔇 Unmute interviewer" : "🔈 Mute interviewer"}
              </button>
            )}
          </div>

          {!rec.supported && (
            <p className="muted small">Voice answers need Chrome or Edge. You can answer by text here.</p>
          )}

          {mode === "voice" && (
            <div className="mic-row">
              <button
                type="button"
                className={`mic ${rec.listening ? "on" : ""}`}
                onClick={toggleMic}
                aria-pressed={rec.listening}
                disabled={thinking}
              >
                {rec.listening ? "■ Stop recording" : "● Start speaking"}
              </button>
              <span className="muted small" role="status">
                {rec.listening
                  ? "Listening… speak naturally, then stop to review your answer."
                  : draft
                    ? "Review or edit the transcript, then send."
                    : "Press start and answer out loud."}
              </span>
            </div>
          )}
          {rec.error && (
            <p className="error" role="alert">
              {rec.error}
            </p>
          )}

          <label htmlFor="answer" className="sr-only">
            Your answer
          </label>
          <textarea
            id="answer"
            ref={inputRef}
            rows={4}
            maxLength={5000}
            placeholder={
              mode === "voice" ? "Your spoken answer appears here…" : "Type your answer… (Ctrl+Enter to send)"
            }
            value={shown}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            readOnly={rec.listening}
            disabled={thinking}
            className={rec.listening ? "listening" : ""}
            autoFocus={mode === "text"}
          />
          <div className="composer-actions">
            {mode === "voice" && (
              <small className="muted">Audio is transcribed by your browser and never stored by MockMate.</small>
            )}
            <button className="primary" type="submit" disabled={thinking || !draft.trim()}>
              Send
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
