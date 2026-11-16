from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import get_settings
from app.db import get_db
from app.models import InterviewSession, User
from app.usage import daily_usage, spent_today

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class DayUsage(BaseModel):
    date: str
    cost_usd: float
    calls: int
    failed_calls: int
    tokens: int
    sessions: int
    avg_cost_per_session: float | None


class SessionCost(BaseModel):
    id: str
    user_email: str | None
    role: str
    status: str
    questions_asked: int
    total_tokens: int
    cost_usd: float


class UsageOut(BaseModel):
    spent_today_usd: float
    daily_cap_usd: float
    days: list[DayUsage]
    recent_sessions: list[SessionCost]


@router.get("/usage")
def usage(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)) -> UsageOut:
    """FR-61: token usage and cost per session, with daily totals."""
    recent = db.execute(
        select(InterviewSession, User.email)
        .outerjoin(User, User.id == InterviewSession.user_id)
        .order_by(InterviewSession.started_at.desc())
        .limit(50)
    ).all()
    return UsageOut(
        spent_today_usd=round(spent_today(db), 4),
        daily_cap_usd=get_settings().daily_cost_cap_usd,
        days=[DayUsage(**d) for d in daily_usage(db, days)],
        recent_sessions=[
            SessionCost(
                id=s.id,
                user_email=email,
                role=s.role,
                status=s.status,
                questions_asked=s.questions_asked,
                total_tokens=s.total_tokens,
                cost_usd=round(s.cost_usd, 4),
            )
            for s, email in recent
        ],
    )
