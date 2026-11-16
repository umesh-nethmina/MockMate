from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.orm import Session

from app import orchestrator
from app.config import get_settings
from app.db import get_db
from app.llm import LLM, get_llm
from app.models import InterviewSession

router = APIRouter(prefix="/sessions", tags=["sessions"])

Text = Annotated[str, StringConstraints(strip_whitespace=True)]


# ---------- schemas ----------

class StartSessionRequest(BaseModel):
    role: Annotated[Text, StringConstraints(min_length=2, max_length=100)]  # FR-03
    level: Literal["intern", "junior", "mid"]  # FR-04
    job_description: Annotated[Text, StringConstraints(max_length=5000)] = ""  # FR-05
    question_limit: int | None = Field(default=None, ge=1, le=20)  # FR-14


class AnswerRequest(BaseModel):
    text: Annotated[Text, StringConstraints(min_length=1, max_length=5000)]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    speaker: str
    kind: str
    round: str
    topic: str | None
    text: str
    created_at: datetime


class TurnResponse(BaseModel):
    session_id: str
    message: MessageOut
    done: bool
    questions_asked: int
    question_limit: int


class SessionOut(BaseModel):
    id: str
    role: str
    level: str
    job_description: str
    status: str
    questions_asked: int
    question_limit: int
    started_at: datetime
    has_report: bool
    messages: list[MessageOut]


class QuestionResult(BaseModel):
    question: str
    topic: str | None
    answer: str
    correctness: int
    clarity: int
    depth: int
    average: float
    feedback: str
    model_answer: str


class ReportOut(BaseModel):
    session_id: str
    role: str
    level: str
    overall_score: float
    strengths: list[str]
    weaknesses: list[str]
    summary: str
    questions: list[QuestionResult]
    total_tokens: int
    cost_usd: float
    created_at: datetime


# ---------- helpers ----------

def _get_session(db: Session, session_id: str) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return session


def _turn(session: InterviewSession, message, done: bool) -> TurnResponse:
    return TurnResponse(
        session_id=session.id,
        message=MessageOut.model_validate(message),
        done=done,
        questions_asked=session.questions_asked,
        question_limit=session.question_limit,
    )


def _report_out(session: InterviewSession) -> ReportOut:
    report = session.report
    assert report is not None
    by_id = {m.id: m for m in session.messages}
    questions = []
    for ev in session.evaluations:
        answer = by_id[ev.message_id]
        question = orchestrator.question_for(session, answer)
        questions.append(
            QuestionResult(
                question=question.text,
                topic=ev.topic,
                answer=answer.text,
                correctness=ev.correctness,
                clarity=ev.clarity,
                depth=ev.depth,
                average=ev.average,
                feedback=ev.feedback,
                model_answer=ev.model_answer,
            )
        )
    return ReportOut(
        session_id=session.id,
        role=session.role,
        level=session.level,
        overall_score=report.overall_score,
        strengths=report.strengths,
        weaknesses=report.weaknesses,
        summary=report.recommendation,
        questions=questions,
        total_tokens=session.total_tokens,
        cost_usd=round(session.cost_usd, 4),
        created_at=report.created_at,
    )


# ---------- routes ----------

@router.post("", status_code=status.HTTP_201_CREATED)
def start_session(
    body: StartSessionRequest, db: Session = Depends(get_db), llm: LLM = Depends(get_llm)
) -> TurnResponse:
    session, first = orchestrator.start_session(
        db,
        llm,
        role=body.role,
        level=body.level,
        job_description=body.job_description,
        question_limit=body.question_limit or get_settings().default_question_limit,
    )
    return _turn(session, first, done=False)


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)) -> SessionOut:
    s = _get_session(db, session_id)
    return SessionOut(
        id=s.id,
        role=s.role,
        level=s.level,
        job_description=s.job_description,
        status=s.status,
        questions_asked=s.questions_asked,
        question_limit=s.question_limit,
        started_at=s.started_at,
        has_report=s.report is not None,
        messages=[MessageOut.model_validate(m) for m in s.messages],
    )


@router.post("/{session_id}/answer")
def submit_answer(
    session_id: str,
    body: AnswerRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    llm: LLM = Depends(get_llm),
) -> TurnResponse:
    session = _get_session(db, session_id)
    reply, done, answer_id = orchestrator.submit_answer(db, llm, session, body.text)
    if answer_id is not None:
        background.add_task(orchestrator.evaluate_in_background, llm, session.id, answer_id)
    return _turn(session, reply, done)


@router.post("/{session_id}/end")
def end_session(session_id: str, db: Session = Depends(get_db), llm: LLM = Depends(get_llm)) -> ReportOut:
    session = _get_session(db, session_id)
    orchestrator.end_session(db, llm, session)
    return _report_out(session)


@router.get("/{session_id}/report")
def get_report(session_id: str, db: Session = Depends(get_db)) -> ReportOut:
    session = _get_session(db, session_id)
    if session.report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not ready - end the session first")
    return _report_out(session)
