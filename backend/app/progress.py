"""Progress across sessions (FR-51) and weak topics for personalising the next session (FR-52).

Plain Python over stored evaluations; no Claude calls.
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Evaluation, InterviewSession, Message, Report

HISTORY_SESSIONS = 10  # weak topics come from the most recent sessions only, so old weaknesses fade out
WEAK_BELOW = 6.5  # average of correctness, clarity and depth
FOCUS_PER_SESSION = 2
DASHBOARD_TOPICS = 5


def _tokens(topic: str) -> set[str]:
    words = re.sub(r"[^a-z0-9+#]+", " ", topic.lower()).split()
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}  # "APIs" ~ "API"


def topic_key(topic: str) -> str:
    """Order- and plural-insensitive key, so "Python generators" and "generators in python" group together."""
    return " ".join(sorted(_tokens(topic)))


def same_topic(a: str, b: str) -> bool:
    """Loose match used to tell whether a weak topic was covered: one label's words contain the other's."""
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb) and (ta <= tb or tb <= ta)


@dataclass
class TopicStat:
    topic: str  # most recent wording
    round: str
    answers: int
    average: float
    last_seen: datetime


def topic_stats(db: Session, user_id: int, sessions: int = HISTORY_SESSIONS) -> list[TopicStat]:
    """Average score per topic over the user's most recent sessions, weakest first."""
    recent = list(
        db.scalars(
            select(InterviewSession.id)
            .join(Evaluation, Evaluation.session_id == InterviewSession.id)
            .where(InterviewSession.user_id == user_id)
            .group_by(InterviewSession.id)
            .order_by(InterviewSession.started_at.desc())
            .limit(sessions)
        )
    )
    if not recent:
        return []
    rows = db.execute(
        select(Evaluation, Message.round, InterviewSession.started_at)
        .join(Message, Message.id == Evaluation.message_id)
        .join(InterviewSession, InterviewSession.id == Evaluation.session_id)
        .where(Evaluation.session_id.in_(recent), Evaluation.topic.is_not(None))
        .order_by(InterviewSession.started_at, Evaluation.id)
    ).all()
    stats: dict[tuple[str, str], dict] = {}
    for ev, rnd, started in rows:
        key = (topic_key(ev.topic), rnd)
        if not key[0]:
            continue
        s = stats.setdefault(key, {"scores": [], "topic": ev.topic, "last": started})
        s["scores"].append(ev.average)
        s["topic"], s["last"] = ev.topic, started  # rows are oldest first: keep the latest wording
    out = [
        TopicStat(s["topic"], rnd, len(s["scores"]), round(sum(s["scores"]) / len(s["scores"]), 1), s["last"])
        for (_, rnd), s in stats.items()
    ]
    return sorted(out, key=lambda t: (t.average, -t.answers))


def weak_topics(stats: list[TopicStat], rounds: tuple[str, ...] | None = None, limit: int = DASHBOARD_TOPICS):
    return [t for t in stats if t.average < WEAK_BELOW and (rounds is None or t.round in rounds)][:limit]


ROUNDS_FOR_TYPE = {"full": ("hr", "technical"), "hr": ("hr",), "technical": ("technical",)}


def focus_topics_for(db: Session, user_id: int, session_type: str) -> list[dict]:
    """FR-52: the weakest topics this session should revisit, snapshotted on the session."""
    rounds = ROUNDS_FOR_TYPE.get(session_type)
    if not rounds:
        return []
    picked = weak_topics(topic_stats(db, user_id), rounds, FOCUS_PER_SESSION)
    return [{"topic": t.topic, "round": t.round, "average": t.average} for t in picked]


def progress(db: Session, user_id: int) -> dict:
    """FR-51: score trend, weakest topics and per-dimension averages."""
    reported = db.execute(
        select(InterviewSession, Report)
        .join(Report, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == user_id)
        .order_by(InterviewSession.started_at)
    ).all()
    trend = [
        {
            "session_id": s.id,
            "date": s.started_at,
            "role": s.role,
            "session_type": s.session_type,
            "score": r.overall_score,
        }
        for s, r in reported
        if r.overall_score > 0
    ]
    scores = [t["score"] for t in trend]
    last, previous = scores[-5:], scores[-10:-5]

    evals = list(
        db.scalars(
            select(Evaluation).join(InterviewSession).where(InterviewSession.user_id == user_id)
        )
    )

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 1) if values else None

    stats = topic_stats(db, user_id)
    return {
        "sessions_completed": len(trend),
        "answers_scored": len(evals),
        "average_score": avg(scores),
        "recent_average": avg(last),
        "previous_average": avg(previous),
        "trend": trend,
        "dimensions": {
            "correctness": avg([e.correctness for e in evals]),
            "clarity": avg([e.clarity for e in evals]),
            "depth": avg([e.depth for e in evals]),
        },
        "weakest_topics": [asdict(t) for t in weak_topics(stats)],
        "strongest_topics": [asdict(t) for t in sorted(stats, key=lambda t: -t.average)[:3] if t.average >= 7],
    }
