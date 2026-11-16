"""Usage and cost accounting: daily totals (FR-61) and the daily cost cap (FR-62)."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import InterviewSession, LlmCall


class DailyCapReached(Exception):
    user_message = "MockMate has reached today's practice limit. Please come back tomorrow."


def _start_of_today() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


def spent_today(db: Session) -> float:
    query = select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(LlmCall.created_at >= _start_of_today())
    total = db.scalar(query)
    return float(total or 0.0)


def check_daily_cap(db: Session) -> None:
    """Called before a new session starts; sessions already running are allowed to finish."""
    if spent_today(db) >= get_settings().daily_cost_cap_usd:
        raise DailyCapReached()


def daily_usage(db: Session, days: int) -> list[dict]:
    since = _start_of_today() - timedelta(days=days - 1)
    calls = db.execute(
        select(LlmCall.created_at, LlmCall.cost_usd, LlmCall.input_tokens, LlmCall.output_tokens,
               LlmCall.cache_read_tokens, LlmCall.cache_write_tokens, LlmCall.ok)
        .where(LlmCall.created_at >= since)
    ).all()
    sessions = db.execute(select(InterviewSession.started_at).where(InterviewSession.started_at >= since)).all()

    totals: dict[date, dict] = defaultdict(lambda: {"cost_usd": 0.0, "calls": 0, "failed_calls": 0, "tokens": 0,
                                                    "sessions": 0})
    for created, cost, i, o, cr, cw, ok in calls:
        day = totals[created.date()]
        day["cost_usd"] += cost
        day["calls"] += 1
        day["failed_calls"] += 0 if ok else 1
        day["tokens"] += i + o + cr + cw
    for (started,) in sessions:
        totals[started.date()]["sessions"] += 1

    out = []
    for n in range(days):
        d = (since + timedelta(days=n)).date()
        row = totals.get(d, {"cost_usd": 0.0, "calls": 0, "failed_calls": 0, "tokens": 0, "sessions": 0})
        sessions_n = row["sessions"]
        out.append(
            {
                "date": d.isoformat(),
                **row,
                "cost_usd": round(row["cost_usd"], 4),
                "avg_cost_per_session": round(row["cost_usd"] / sessions_n, 4) if sessions_n else None,
            }
        )
    return out
