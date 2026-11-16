from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

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
