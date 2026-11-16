import { useEffect, useState } from "react";
import { getUsage, type Usage } from "../api";

const usd = (n: number) => `$${n.toFixed(n < 1 ? 3 : 2)}`;

export default function AdminPage() {
  const [days, setDays] = useState(7);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUsage(days)
      .then(setUsage)
      .catch((e: Error) => setError(e.message));
  }, [days]);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!usage) return <p className="muted">Loading usage…</p>;

  const pct = Math.min(100, (usage.spent_today_usd / usage.daily_cap_usd) * 100);

  return (
    <>
      <h1>Usage and cost</h1>

      <section className="card">
        <div className="row spread">
          <strong>Today</strong>
          <span>
            {usd(usage.spent_today_usd)} of {usd(usage.daily_cap_usd)} daily cap
          </span>
        </div>
        <div className="progress big-progress" aria-label={`${pct.toFixed(0)}% of daily cap used`}>
          <div style={{ width: `${pct}%` }} className={pct >= 90 ? "over" : ""} />
        </div>
        <p className="muted small">New interviews are blocked once the cap is reached; running ones can finish.</p>
      </section>

      <section className="card">
        <div className="row spread">
          <h2 className="h3">Daily totals</h2>
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th className="num">Sessions</th>
                <th className="num">Calls</th>
                <th className="num">Failed</th>
                <th className="num">Tokens</th>
                <th className="num">Cost</th>
                <th className="num">Per session</th>
              </tr>
            </thead>
            <tbody>
              {[...usage.days].reverse().map((d) => (
                <tr key={d.date}>
                  <td>{d.date}</td>
                  <td className="num">{d.sessions}</td>
                  <td className="num">{d.calls}</td>
                  <td className="num">{d.failed_calls}</td>
                  <td className="num">{d.tokens.toLocaleString()}</td>
                  <td className="num">{usd(d.cost_usd)}</td>
                  <td className="num">{d.avg_cost_per_session !== null ? usd(d.avg_cost_per_session) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h2 className="h3">Recent sessions</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Role</th>
                <th>Status</th>
                <th className="num">Questions</th>
                <th className="num">Tokens</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {usage.recent_sessions.map((s) => (
                <tr key={s.id}>
                  <td>{s.user_email ?? "guest"}</td>
                  <td>{s.role}</td>
                  <td>{s.status}</td>
                  <td className="num">{s.questions_asked}</td>
                  <td className="num">{s.total_tokens.toLocaleString()}</td>
                  <td className="num">{usd(s.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
