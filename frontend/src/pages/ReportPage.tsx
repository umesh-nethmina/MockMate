import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getReport, type Delivery, type Report } from "../api";

function scoreClass(score: number) {
  if (score >= 7) return "good";
  if (score >= 5) return "ok";
  return "low";
}

const PACE = { slow: "a bit slow", good: "good pace", fast: "a bit fast" } as const;
const PACE_TIP = {
  slow: "Try to keep momentum: plan the first sentence, then keep going.",
  good: "A clear, comfortable pace - keep it up.",
  fast: "Slow down a little and pause between points so the interviewer can follow.",
} as const;

const fillerList = (words: Record<string, number>) =>
  Object.entries(words)
    .map(([w, n]) => `"${w}" ×${n}`)
    .join(", ");

function DeliveryCard({ d }: { d: Delivery }) {
  return (
    <section className="card">
      <h2 className="h3">How you spoke</h2>
      <dl className="metrics">
        <div>
          <dt>Speaking pace</dt>
          <dd className={d.pace === "good" ? "good" : d.pace ? "ok" : ""}>
            {d.avg_wpm !== null ? `${Math.round(d.avg_wpm)} wpm` : "-"}
          </dd>
          <small className="muted">{d.pace ? PACE[d.pace] : "not enough speech to measure"} · aim for 110-160</small>
        </div>
        <div>
          <dt>Filler words</dt>
          <dd className={d.total_fillers <= d.voice_answers ? "good" : "ok"}>{d.total_fillers}</dd>
          <small className="muted">
            {d.total_fillers ? `most used: ${fillerList(d.top_fillers)}` : "none detected"}
          </small>
        </div>
        <div>
          <dt>Answer length</dt>
          <dd>{Math.round(d.avg_words_per_answer)}</dd>
          <small className="muted">words per answer on average</small>
        </div>
      </dl>
      {d.pace && <p className="small">{PACE_TIP[d.pace]}</p>}
      <p className="muted small">
        Based on {d.voice_answers} spoken answer{d.voice_answers === 1 ? "" : "s"}. Browsers often leave out "um" and
        "uh" when transcribing, so the real filler count may be higher.
      </p>
    </section>
  );
}

export default function ReportPage() {
  const { id = "" } = useParams();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getReport(id)
      .then(setReport)
      .catch((e: Error) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div>
        <p className="error" role="alert">
          {error}
        </p>
        <Link to={`/interview/${id}`}>Back to the interview</Link>
      </div>
    );
  }
  if (!report) return <p className="muted">Loading report…</p>;

  return (
    <div className="report">
      <section className="card score-card">
        <div className={`overall ${scoreClass(report.overall_score)}`}>
          <span className="big">{report.overall_score.toFixed(1)}</span>
          <span className="muted">/ 10</span>
        </div>
        <div>
          <h1 className="h2">
            {report.role} · {report.level}
          </h1>
          <p>{report.summary}</p>
        </div>
      </section>

      {report.questions.length > 0 && (
        <>
          <div className="two-col">
            <section className="card">
              <h2 className="h3">Strengths</h2>
              <ul>
                {report.strengths.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </section>
            <section className="card">
              <h2 className="h3">To improve</h2>
              <ul>
                {report.weaknesses.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </section>
          </div>

          {report.delivery && report.delivery.voice_answers > 0 && <DeliveryCard d={report.delivery} />}

          <section className="card">
            <h2 className="h3">Score per question</h2>
            <ol className="bars">
              {report.questions.map((q, i) => (
                <li key={i}>
                  <span className="bar-label">
                    Q{i + 1} <span className="muted">{q.topic}</span>
                  </span>
                  <span className="bar-track" aria-hidden="true">
                    <span className={`bar ${scoreClass(q.average)}`} style={{ width: `${q.average * 10}%` }} />
                  </span>
                  <span className="bar-value">{q.average.toFixed(1)}</span>
                </li>
              ))}
            </ol>
          </section>

          <section>
            <h2 className="h3">Question by question</h2>
            {report.questions.map((q, i) => (
              <details key={i} className="card question">
                <summary>
                  <span>
                    <span className="round-tag">{q.round === "hr" ? "HR" : "Tech"}</span> Q{i + 1}. {q.question}
                  </span>
                  <span className={`pill ${scoreClass(q.average)}`}>{q.average.toFixed(1)}</span>
                </summary>
                <dl className="scores">
                  <div>
                    <dt>Correctness</dt>
                    <dd>{q.correctness}</dd>
                  </div>
                  <div>
                    <dt>Clarity</dt>
                    <dd>{q.clarity}</dd>
                  </div>
                  <div>
                    <dt>Depth</dt>
                    <dd>{q.depth}</dd>
                  </div>
                </dl>
                {q.star && (
                  <div className="star" aria-label="STAR structure">
                    {(["situation", "task", "action", "result"] as const).map((part) => (
                      <span key={part} className={`chip ${q.star![part] ? "yes" : "no"}`}>
                        {q.star![part] ? "✓" : "✗"} {part[0].toUpperCase() + part.slice(1)}
                      </span>
                    ))}
                  </div>
                )}
                <h3 className="h4">Your answer {q.is_voice && <span className="muted">(spoken)</span>}</h3>
                {q.is_voice && (
                  <p className="muted small">
                    {q.word_count} words
                    {q.wpm !== null && ` · ${Math.round(q.wpm)} words/min (${PACE[q.pace ?? "good"]})`}
                    {` · ${q.filler_count ?? 0} filler${q.filler_count === 1 ? "" : "s"}`}
                    {q.filler_words && Object.keys(q.filler_words).length > 0 && `: ${fillerList(q.filler_words)}`}
                  </p>
                )}
                <p className="quote">{q.answer}</p>
                <h3 className="h4">Feedback</h3>
                <p>{q.feedback}</p>
                <h3 className="h4">Model answer</h3>
                <p className="quote model">{q.model_answer}</p>
              </details>
            ))}
          </section>
        </>
      )}

      <div className="actions">
        <Link className="button primary" to="/">
          Start another interview
        </Link>
        <span className="muted small">
          {report.total_tokens.toLocaleString()} tokens · ${report.cost_usd.toFixed(3)}
        </span>
      </div>
    </div>
  );
}
