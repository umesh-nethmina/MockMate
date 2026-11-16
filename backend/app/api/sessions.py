from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import coding, orchestrator
from app.api.auth import purge_expired_guests
from app.auth import get_current_user
from app.config import get_settings
from app.db import get_db
from app.llm import LLM, get_llm
from app.models import CV, InterviewSession, User
from app.tools.sandbox import Sandbox, get_sandbox
from app.tools.speech_metrics import pace_label, word_count
from app.usage import check_daily_cap

router = APIRouter(prefix="/sessions", tags=["sessions"])

Text = Annotated[str, StringConstraints(strip_whitespace=True)]


# ---------- schemas ----------

class StartSessionRequest(BaseModel):
    role: Annotated[Text, StringConstraints(min_length=2, max_length=100)]  # FR-03
    level: Literal["intern", "junior", "mid"]  # FR-04
    job_description: Annotated[Text, StringConstraints(max_length=5000)] = ""  # FR-05
    cv_id: int | None = None  # FR-06
    session_type: Literal["full", "hr", "technical", "coding"] = "full"  # FR-07
    personality: Literal["friendly_hr", "strict_tech_lead", "fast_paced_founder"] = "friendly_hr"  # FR-08
    question_limit: int | None = Field(default=None, ge=1, le=20)  # FR-14


class AnswerRequest(BaseModel):
    text: Annotated[Text, StringConstraints(min_length=1, max_length=5000)]
    # Voice answers (FR-20): raw transcript before the candidate's edits, and time spent speaking
    is_voice: bool = False
    voice_transcript: Annotated[str, StringConstraints(max_length=5000)] | None = None
    speech_seconds: float | None = Field(default=None, gt=0, le=1800)


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
    session_type: str
    personality: str
    has_cv: bool
    job_description: str
    status: str
    questions_asked: int
    question_limit: int
    started_at: datetime
    has_report: bool
    messages: list[MessageOut]


class QuestionResult(BaseModel):
    kind: str  # "answer", or "code" for a coding submission
    question: str
    round: str
    topic: str | None
    answer: str
    correctness: int
    clarity: int
    depth: int
    average: float
    star: dict[str, bool] | None
    feedback: str
    model_answer: str
    # Delivery (FR-43); speech fields are null for typed answers
    is_voice: bool
    word_count: int
    wpm: float | None
    pace: str | None
    filler_count: int | None
    filler_words: dict[str, int] | None
    # Coding submissions (FR-32, FR-33)
    language: str | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    hints_used: int | None = None


class DeliverySummary(BaseModel):
    voice_answers: int
    avg_wpm: float | None
    pace: str | None
    total_fillers: int
    top_fillers: dict[str, int]
    avg_words_per_answer: float


class ReportOut(BaseModel):
    session_id: str
    role: str
    level: str
    session_type: str
    overall_score: float
    strengths: list[str]
    weaknesses: list[str]
    summary: str
    questions: list[QuestionResult]
    delivery: DeliverySummary | None
    total_tokens: int
    cost_usd: float
    created_at: datetime


# ---------- helpers ----------

def get_owned_session(
    session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:  # same 404 either way: don't reveal other users' ids
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
    submission = coding.last_submission(session)
    questions = []
    for ev in session.evaluations:
        answer = by_id[ev.message_id]
        question = orchestrator.question_for(session, answer).text
        code_fields: dict = {}
        if answer.kind == "code" and submission is not None:
            if session.problem is not None:
                question = f"{session.problem.title}: {session.problem.statement}"
            code_fields = {
                "language": submission.language,
                "tests_passed": submission.passed + submission.hidden_passed,
                "tests_total": submission.total + submission.hidden_total,
                "hints_used": session.hints_used,
            }
        questions.append(
            QuestionResult(
                kind=answer.kind,
                question=question,
                round=answer.round,
                topic=ev.topic,
                answer=answer.text,
                correctness=ev.correctness,
                clarity=ev.clarity,
                depth=ev.depth,
                average=ev.average,
                star=ev.star_flags,
                feedback=ev.feedback,
                model_answer=ev.model_answer,
                is_voice=answer.is_voice,
                word_count=word_count(answer.text),
                wpm=answer.wpm,
                pace=pace_label(answer.wpm),
                filler_count=answer.filler_count,
                filler_words=answer.filler_words,
                **code_fields,
            )
        )
    return ReportOut(
        session_id=session.id,
        role=session.role,
        level=session.level,
        session_type=session.session_type,
        overall_score=report.overall_score,
        strengths=report.strengths,
        weaknesses=report.weaknesses,
        summary=report.recommendation,
        questions=questions,
        delivery=_delivery(questions),
        total_tokens=session.total_tokens,
        cost_usd=round(session.cost_usd, 4),
        created_at=report.created_at,
    )


def _delivery(questions: list[QuestionResult]) -> DeliverySummary | None:
    if not questions:
        return None
    questions = [q for q in questions if q.kind == "answer"]  # code is not spoken delivery
    if not questions:
        return None
    voice = [q for q in questions if q.is_voice]
    rates = [q.wpm for q in voice if q.wpm is not None]
    avg_wpm = round(sum(rates) / len(rates), 1) if rates else None
    fillers: dict[str, int] = {}
    for q in voice:
        for word, n in (q.filler_words or {}).items():
            fillers[word] = fillers.get(word, 0) + n
    top = dict(sorted(fillers.items(), key=lambda kv: -kv[1])[:5])
    return DeliverySummary(
        voice_answers=len(voice),
        avg_wpm=avg_wpm,
        pace=pace_label(avg_wpm),
        total_fillers=sum(fillers.values()),
        top_fillers=top,
        avg_words_per_answer=round(sum(q.word_count for q in questions) / len(questions), 1),
    )


# ---------- routes ----------

@router.post("", status_code=status.HTTP_201_CREATED)
def start_session(
    body: StartSessionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLM = Depends(get_llm),
    sandbox: Sandbox = Depends(get_sandbox),
) -> TurnResponse:
    settings = get_settings()
    purge_expired_guests(db)
    check_daily_cap(db)  # FR-62

    question_limit = body.question_limit or settings.default_question_limit
    if user.is_guest:  # FR-02: one short text interview
        has_session = db.scalar(select(func.count()).where(InterviewSession.user_id == user.id))
        if has_session:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Guests can try one interview. Create a free account to keep practising."
            )
        question_limit = min(question_limit, settings.guest_question_limit)
        if body.session_type == "coding":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Create a free account to try the coding round.")

    if body.session_type == "coding":  # FR-30: no Claude call to start; the problem is picked by rule
        if not sandbox.available():
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "The coding round is not available right now. Try another type."
            )
        problem = coding.pick_problem(db, user.id, body.level)
        if problem is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No coding problems are set up yet.")
        session, first = coding.start_coding_session(
            db,
            user_id=user.id,
            problem=problem,
            role=body.role,
            level=body.level,
            job_description=body.job_description,
            personality=body.personality,
        )
        return _turn(session, first, done=False)

    cv_text = ""
    if body.cv_id is not None:
        cv = db.get(CV, body.cv_id)
        if cv is None or cv.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "CV not found")
        cv_text = cv.extracted_text

    session, first = orchestrator.start_session(
        db,
        llm,
        user_id=user.id,
        role=body.role,
        level=body.level,
        job_description=body.job_description,
        question_limit=question_limit,
        session_type=body.session_type,
        personality=body.personality,
        cv_id=body.cv_id,
        cv_text=cv_text,
    )
    return _turn(session, first, done=False)


@router.get("/{session_id}")
def get_session(s: InterviewSession = Depends(get_owned_session)) -> SessionOut:
    return SessionOut(
        id=s.id,
        role=s.role,
        level=s.level,
        session_type=s.session_type,
        personality=s.personality,
        has_cv=bool(s.cv_text.strip()),
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
    body: AnswerRequest,
    background: BackgroundTasks,
    session: InterviewSession = Depends(get_owned_session),
    db: Session = Depends(get_db),
    llm: LLM = Depends(get_llm),
) -> TurnResponse:
    voice = None
    if body.is_voice:
        voice = orchestrator.VoiceInput(transcript=body.voice_transcript or body.text, seconds=body.speech_seconds)
    reply, done, answer_id = orchestrator.submit_answer(db, llm, session, body.text, voice)
    if answer_id is not None:
        background.add_task(orchestrator.evaluate_in_background, llm, session.id, answer_id)
    return _turn(session, reply, done)


@router.post("/{session_id}/end")
def end_session(
    session: InterviewSession = Depends(get_owned_session),
    db: Session = Depends(get_db),
    llm: LLM = Depends(get_llm),
) -> ReportOut:
    orchestrator.end_session(db, llm, session)
    return _report_out(session)


@router.get("/{session_id}/report")
def get_report(session: InterviewSession = Depends(get_owned_session)) -> ReportOut:
    if session.report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not ready - end the session first")
    return _report_out(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session: InterviewSession = Depends(get_owned_session), db: Session = Depends(get_db)) -> Response:
    """FR-54: delete one session with its messages, evaluations and report."""
    db.delete(session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
