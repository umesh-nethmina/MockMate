// FR-51: progress dashboard - headline numbers, score trend, weakest topics and score per dimension.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getProgress, type Progress, type TopicStat } from "../api";

const fmt = (n: number | null) => (n === null ? "-" : n.toFixed(1));
const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="tile">
      <span className="muted small">{label}</span>
      <strong className="tile-value">{value}</strong>
      {note && <span className="muted small">{note}</span>}
    </div>
  );
}

/** Single-series line chart of overall scores (0-10), with a per-point hover tooltip and a table toggle. */
function ScoreTrend({ trend }: { trend: Progress["trend"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const W = 640;
  const H = 220;
  const pad = { l: 32, r: 16, t: 12, b: 28 };
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const x = (i: number) => pad.l + (trend.length === 1 ? iw / 2 : (i / (trend.length - 1)) * iw);
  const y = (v: number) => pad.t + ih - (v / 10) * ih;
  const path = trend.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(" ");
  const labelEvery = Math.max(1, Math.ceil(trend.length / 6));
  const h = hover !== null ? trend[hover] : null;

  return (
    <section className="card">
      <div className="row spread">
        <h2 className="h3">Score over time</h2>
        <button type="button" className="link small" onClick={() => setAsTable(!asTable)}>
          {asTable ? "Show chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Interview</th>
                <th className="num">Score</th>
              </tr>
            </thead>
            <tbody>
              {[...trend].reverse().map((p) => (
                <tr key={p.session_id}>
                  <td>{day(p.date)}</td>
                  <td>
                    <Link to={`/report/${p.session_id}`}>
                      {p.role} · {p.session_type}
                    </Link>
                  </td>
                  <td className="num">{p.score.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-wrap">
          <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Overall score per interview, 0 to 10">
            {[0, 5, 10].map((v) => (
              <g key={v}>
                <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className="grid" />
                <text x={pad.l - 8} y={y(v) + 4} className="axis" textAnchor="end">
                  {v}
                </text>
              </g>
            ))}
            {trend.map((p, i) =>
              i % labelEvery === 0 || i === trend.length - 1 ? (
                <text key={p.session_id} x={x(i)} y={H - 8} className="axis" textAnchor="middle">
                  {day(p.date)}
                </text>
              ) : null,
            )}
            {h && hover !== null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} className="crosshair" />}
            <path d={path} className="series-line" />
            {trend.map((p, i) => (
              <g key={p.session_id}>
                <circle cx={x(i)} cy={y(p.score)} r={hover === i ? 5.5 : 4} className="series-dot" />
                <circle
                  cx={x(i)}
                  cy={y(p.score)}
                  r={14}
                  className="hit"
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  tabIndex={0}
                  aria-label={`${day(p.date)}: ${p.score.toFixed(1)} out of 10, ${p.role}`}
                />
              </g>
            ))}
          </svg>
          {h && hover !== null && (
            <div
              className="tooltip"
              style={{ left: `${(x(hover) / W) * 100}%`, top: `${(y(h.score) / H) * 100}%` }}
              role="status"
            >
              <strong>{h.score.toFixed(1)}</strong> / 10
              <br />
              <span className="muted">
                {day(h.date)} · {h.role} · {h.session_type}
              </span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** Horizontal bars on a fixed 0-10 scale, labelled with the value; tooltip gives the answer count. */
function Bars({ rows }: { rows: { label: string; value: number; detail: string }[] }) {
  return (
    <ul className="hbars">
      {rows.map((r) => (
        <li key={r.label} title={r.detail}>
          <span className="hbar-label">{r.label}</span>
          <span className="hbar-track" aria-hidden="true">
            <span className="hbar" style={{ width: `${Math.max(2, r.value * 10)}%` }} />
          </span>
          <span className="hbar-value">{r.value.toFixed(1)}</span>
        </li>
      ))}
    </ul>
  );
}

const topicRows = (topics: TopicStat[]) =>
  topics.map((t) => ({
    label: t.topic,
    value: t.average,
    detail: `${t.answers} answer${t.answers === 1 ? "" : "s"} · ${t.round} · last ${day(t.last_seen)}`,
  }));

export default function ProgressPage() {
  const [p, setP] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProgress()
      .then(setP)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!p) return <p className="muted">Loading your progress…</p>;

  if (p.sessions_completed === 0) {
    return (
      <section className="card center">
        <h1 className="h2">Your progress</h1>
        <p>Finish an interview to see your scores and weakest topics here.</p>
        <Link className="button primary" to="/">
          Start an interview
        </Link>
      </section>
    );
  }

  const change =
    p.recent_average !== null && p.previous_average !== null ? p.recent_average - p.previous_average : null;
  const dims = p.dimensions;

  return (
    <>
      <h1>Your progress</h1>
      <div className="tiles">
        <Tile label="Interviews finished" value={String(p.sessions_completed)} note={`${p.answers_scored} answers scored`} />
        <Tile label="Average score" value={fmt(p.recent_average)} note="last 5 interviews, out of 10" />
        <Tile
          label="Change"
          value={change === null ? "-" : `${change >= 0 ? "▲ +" : "▼ "}${change.toFixed(1)}`}
          note={change === null ? "needs 6+ interviews" : "vs the 5 before"}
        />
      </div>

      <ScoreTrend trend={p.trend} />

      <div className="two-col">
        <section className="card">
          <h2 className="h3">Weakest topics</h2>
          {p.weakest_topics.length ? (
            <>
              <Bars rows={topicRows(p.weakest_topics)} />
              <p className="muted small">
                Average of correctness, clarity and depth over your last 10 interviews. New interviews revisit these
                automatically.
              </p>
              <Link className="button" to="/">
                Practise these now
              </Link>
            </>
          ) : (
            <p className="muted">No weak topics right now - every topic averages 6.5 or more.</p>
          )}
        </section>
        <section className="card">
          <h2 className="h3">Score by dimension</h2>
          <Bars
            rows={(["correctness", "clarity", "depth"] as const)
              .filter((k) => dims[k] !== null)
              .map((k) => ({ label: k[0].toUpperCase() + k.slice(1), value: dims[k]!, detail: `${k}, all answers` }))}
          />
          {p.strongest_topics.length > 0 && (
            <>
              <h3 className="h4">Strongest topics</h3>
              <Bars rows={topicRows(p.strongest_topics)} />
            </>
          )}
        </section>
      </div>
    </>
  );
}
