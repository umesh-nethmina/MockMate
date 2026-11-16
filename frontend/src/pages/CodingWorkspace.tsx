// Coding round (FR-30..FR-34): problem statement, Monaco editor, run against sample tests, hints, submit.
import Editor, { type OnMount } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";
import { getProblem, requestHint, runCode, submitCode, type CodeLanguage, type CodeRun, type Problem } from "../api";
import { monaco } from "../monaco";
import { readPref, writePref } from "../speech";

const LANGS: { value: CodeLanguage; label: string }[] = [
  { value: "python", label: "Python 3.12" },
  { value: "javascript", label: "JavaScript (Node 22)" },
];
const show = (v: unknown) => JSON.stringify(v);
const draftKey = (id: string, lang: CodeLanguage) => `code.${id}.${lang}`;

function useDarkMode() {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return dark;
}

function Results({ run }: { run: CodeRun }) {
  const samples = run.results.filter((r) => !r.hidden);
  const hidden = run.results.filter((r) => r.hidden);
  return (
    <section className="results" aria-live="polite">
      <div className="row spread">
        <strong>
          {run.kind === "submit" ? "Submission" : "Sample tests"}:{" "}
          {run.status === "ok" ? `${run.passed} of ${run.total} passed` : "did not run"}
        </strong>
        <span className="muted small">{(run.duration_ms / 1000).toFixed(1)} s</span>
      </div>
      {run.message && <p className={run.status === "ok" ? "muted small" : "error"}>{run.message}</p>}
      <ol className="tests">
        {samples.map((r, i) => (
          <li key={i} className={r.ok ? "pass" : "fail"}>
            <span className="mark" aria-label={r.ok ? "passed" : "failed"}>
              {r.ok ? "✓" : "✗"}
            </span>
            <code>({(r.args ?? []).map(show).join(", ")})</code>
            <span className="muted small">
              expected <code>{show(r.expected)}</code>
              {!r.ok && !r.error && (
                <>
                  , got <code>{show(r.output)}</code>
                </>
              )}
            </span>
            {r.error && <span className="error-text small">{r.error}</span>}
            {r.stdout && <pre className="stdout">{r.stdout}</pre>}
          </li>
        ))}
      </ol>
      {run.hidden_total > 0 && (
        <p className="small">
          Hidden tests: {run.hidden_passed} of {run.hidden_total} passed
          {hidden.some((r) => !r.ok) && (
            <span className="muted">
              {" "}
              (failures: {hidden.filter((r) => !r.ok).map((r) => r.error ?? "wrong answer").join(", ")})
            </span>
          )}
        </p>
      )}
    </section>
  );
}

type Props = { sessionId: string; active: boolean; onChanged: () => Promise<void> };

export default function CodingWorkspace({ sessionId, active, onChanged }: Props) {
  const [problem, setProblem] = useState<Problem | null>(null);
  const [lang, setLang] = useState<CodeLanguage>(() => readPref<CodeLanguage>("codeLang", "python"));
  const [code, setCode] = useState("");
  const [run, setRun] = useState<CodeRun | null>(null);
  const [busy, setBusy] = useState<"run" | "submit" | "hint" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dark = useDarkMode();
  const runRef = useRef<() => void>(() => {});

  // Restore: local draft first, then the last code sent to the server, then the starter code (NFR-12)
  function initialCode(p: Problem, l: CodeLanguage) {
    const draft = readPref<string>(draftKey(sessionId, l), "");
    if (draft) return draft;
    if (p.last_run?.language === l) return p.last_run.code;
    return p.starter_code[l];
  }

  useEffect(() => {
    getProblem(sessionId)
      .then((p) => {
        const l = p.last_run?.language ?? readPref<CodeLanguage>("codeLang", "python");
        setProblem(p);
        setLang(l);
        setCode(initialCode(p, l));
        setRun(p.last_run);
      })
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once per session
  }, [sessionId]);

  const locked = !active || !problem || problem.submitted;

  function changeCode(value: string | undefined) {
    const next = value ?? "";
    setCode(next);
    writePref(draftKey(sessionId, lang), next);
  }

  function changeLang(next: CodeLanguage) {
    if (!problem || next === lang) return;
    setLang(next);
    writePref("codeLang", next);
    setCode(initialCode(problem, next));
  }

  function reset() {
    if (!problem || !window.confirm("Replace your code with the starter code?")) return;
    changeCode(problem.starter_code[lang]);
  }

  async function act(kind: "run" | "submit" | "hint") {
    if (!problem || busy || locked) return;
    setBusy(kind);
    setError(null);
    try {
      if (kind === "run") {
        setRun(await runCode(sessionId, lang, code));
      } else if (kind === "hint") {
        const h = await requestHint(sessionId);
        setProblem({ ...problem, hints_used: h.hints_used });
        await onChanged();
      } else {
        const res = await submitCode(sessionId, lang, code);
        setRun(res.run);
        setProblem({ ...problem, submitted: true });
        LANGS.forEach((l) => writePref(draftKey(sessionId, l.value), "")); // the server has the final code
        await onChanged();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  runRef.current = () => void act("run");

  const onMount: OnMount = (editor) => {
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => runRef.current());
  };

  if (!problem) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p className="muted">Loading the coding exercise…</p>
    );
  }

  const fn = problem.function_names[lang];
  const hintsLeft = problem.hints_total - problem.hints_used;

  return (
    <div className="workspace">
      <section className="card problem">
        <div className="row spread">
          <h2 className="h3">{problem.title}</h2>
          <span className={`pill diff-${problem.difficulty}`}>{problem.difficulty}</span>
        </div>
        <p className="muted small">{problem.topic}</p>
        {problem.statement.split("\n\n").map((para, i) => (
          <p key={i}>{para}</p>
        ))}
        <p className="small">
          Write a function <code>{fn}</code>({problem.params.join(", ")}) that returns the answer.
        </p>
        <h3 className="h4">Examples</h3>
        <ul className="examples">
          {problem.samples.map((s, i) => (
            <li key={i}>
              <code>
                {fn}({s.args.map(show).join(", ")}) → {show(s.expected)}
              </code>
            </li>
          ))}
        </ul>
        <p className="muted small">
          {problem.hidden_tests} more hidden test{problem.hidden_tests === 1 ? "" : "s"} run when you submit.
        </p>
      </section>

      <section className="card editor-card">
        <div className="editor-bar">
          <select
            aria-label="Language"
            value={lang}
            onChange={(e) => changeLang(e.target.value as CodeLanguage)}
            disabled={locked}
          >
            {LANGS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
          <button type="button" className="ghost small" onClick={reset} disabled={locked}>
            Reset
          </button>
        </div>
        <div className="editor" aria-label="Code editor">
          <Editor
            height="100%"
            language={lang}
            value={code}
            theme={dark ? "vs-dark" : "vs"}
            onChange={changeCode}
            onMount={onMount}
            options={{
              readOnly: locked,
              minimap: { enabled: false },
              fontSize: 14,
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: lang === "python" ? 4 : 2,
              accessibilitySupport: "auto",
            }}
            loading={<p className="muted">Loading editor…</p>}
          />
        </div>
        <div className="editor-actions">
          <button type="button" onClick={() => void act("run")} disabled={locked || busy !== null}>
            {busy === "run" ? "Running…" : "▶ Run sample tests"}
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => void act("hint")}
            disabled={locked || busy !== null || hintsLeft <= 0}
            title="Each hint lowers your correctness score by one point"
          >
            {busy === "hint" ? "…" : `💡 Hint (${hintsLeft} left)`}
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              if (window.confirm("Submit your final answer? You can't change the code after submitting.")) {
                void act("submit");
              }
            }}
            disabled={locked || busy !== null || !code.trim()}
          >
            {busy === "submit" ? "Submitting…" : problem.submitted ? "Submitted" : "Submit"}
          </button>
        </div>
        <p className="muted small">Ctrl+Enter runs the sample tests. Your code runs in an isolated sandbox.</p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {run && <Results run={run} />}
      </section>
    </div>
  );
}
