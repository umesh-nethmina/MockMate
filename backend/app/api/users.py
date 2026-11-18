from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import progress
from app.api.auth import UserOut, user_out
from app.auth import get_current_user, verify_password
from app.db import get_db
from app.models import InterviewSession, User

router = APIRouter(prefix="/users/me", tags=["users"])


class SessionSummary(BaseModel):
    id: str
    role: str
    level: str
    session_type: str
    status: str
    questions_asked: int
    question_limit: int
    overall_score: float | None
    started_at: datetime


class TopicOut(BaseModel):
    topic: str
    round: str
    answers: int
    average: float
    last_seen: datetime


class TrendPoint(BaseModel):
    session_id: str
    date: datetime
    role: str
    session_type: str
    score: float


class ProgressOut(BaseModel):
    sessions_completed: int
    answers_scored: int
    average_score: float | None
    recent_average: float | None  # last 5 sessions
    previous_average: float | None  # the 5 before those
    trend: list[TrendPoint]
    dimensions: dict[str, float | None]
    weakest_topics: list[TopicOut]
    strongest_topics: list[TopicOut]


class DeleteAccountRequest(BaseModel):
    password: Annotated[str, StringConstraints(max_length=200)] = ""


@router.get("")
def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)


@router.get("/sessions")
def my_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SessionSummary]:
    """FR-50: every session of the logged-in user, newest first."""
    rows = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user.id)
        .options(selectinload(InterviewSession.report))
        .order_by(InterviewSession.started_at.desc())
    )
    return [
        SessionSummary(
            id=s.id,
            role=s.role,
            level=s.level,
            session_type=s.session_type,
            status=s.status,
            questions_asked=s.questions_asked,
            question_limit=s.question_limit,
            overall_score=s.report.overall_score if s.report else None,
            started_at=s.started_at,
        )
        for s in rows
    ]


@router.get("/progress")
def my_progress(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProgressOut:
    """FR-51: score trend, weakest topics and per-dimension averages across the user's sessions."""
    return ProgressOut(**progress.progress(db, user.id))


def _columns(obj, skip: tuple[str, ...] = ()) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns if c.key not in skip}


@router.get("/export")
def export_my_data(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JSONResponse:
    """NFR-10: everything MockMate stores about the user, as one JSON file (no password hash)."""
    sessions = db.scalars(
        select(InterviewSession)
        .where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.started_at)
    )
    data = {
        "exported_at": datetime.now(UTC),
        "format": "mockmate-export-v1",
        "account": _columns(user, skip=("password_hash",)),
        "cvs": [_columns(cv, skip=("user_id",)) for cv in user.cvs],
        "sessions": [
            {
                **_columns(s, skip=("user_id",)),
                "messages": [_columns(m, skip=("session_id",)) for m in s.messages],
                "evaluations": [_columns(e, skip=("session_id",)) for e in s.evaluations],
                "code_runs": [_columns(r, skip=("session_id",)) for r in s.code_runs],
                "report": _columns(s.report, skip=("session_id",)) if s.report else None,
            }
            for s in sessions
        ],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": f'attachment; filename="mockmate-data-{stamp}.json"'},
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: DeleteAccountRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    """FR-54 / UC-04: delete the user, CVs, sessions, messages, evaluations and reports.
    Registered users confirm with their password; guests (no password) can delete straight away."""
    if not user.is_guest and not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password is incorrect")
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
