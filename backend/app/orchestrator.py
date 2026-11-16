"""Orchestrator: deterministic session state machine. It plans each turn (round, difficulty, follow-up
and CV-question rules), routes it to the right agent, enforces question limits (FR-14) and saves state
after every turn (NFR-12). It never calls Claude itself."""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import coding
from app import db as database
from app.agents import evaluator, interviewer
from app.agents.context import InterviewContext
from app.agents.evaluator import AnswerScore, ScoredItem
from app.agents.interviewer import (
    MAX_FOLLOW_UPS_PER_TOPIC,
    CvDue,
    Difficulty,
    InterviewerTurn,
    Round,
    Turn,
    TurnPlan,
)
from app.llm import LLM, LLMError, LLMResult, LLMUsage
from app.models import Evaluation, InterviewSession, LlmCall, Message, Report
from app.tools import speech_metrics

log = logging.getLogger(__name__)

CLOSING_TEXT = "That's the end of our interview - thank you for your time! I'm preparing your report now."
INTERVIEWER_KINDS = {"follow_up": "follow_up", "next_topic": "question", "redirect": "redirect"}
EVAL_WORKERS = 4
SCORED_KINDS = ("answer", "code")  # candidate messages that get an Evaluation
NO_ANSWERS_TEXT = "No answers were given, so there is nothing to score yet. Start a new interview to get feedback."
DIFFICULTIES: list[Difficulty] = ["easy", "medium", "hard"]
HR_SHARE_OF_FULL_INTERVIEW = 3 / 8
CV_QUESTION_BY = 3  # FR-13: ask about a CV project no later than question 3


class SessionStateError(Exception):
    """The request does not fit the session's current state (HTTP 409)."""


@dataclass(frozen=True)
class VoiceInput:
    """A spoken answer: the raw speech-to-text transcript (before edits) and the speaking time."""

    transcript: str
    seconds: float | None


# ---------- planning rules (pure functions, unit-tested) ----------

def round_for(session_type: str, question_limit: int, number: int) -> Round:
    """Round of question `number` (1-based). A full interview runs HR first, then technical (FR-07)."""
    if session_type == "hr":
        return "hr"
    if session_type == "technical":
        return "technical"
    hr_count = max(1, round(question_limit * HR_SHARE_OF_FULL_INTERVIEW))
    return "hr" if number <= hr_count else "technical"


def adjust_difficulty(current: str, qualities: list[str | None]) -> Difficulty:
    """FR-12: one level harder after a strong answer, one level easier after two weak answers in a row."""
    i = DIFFICULTIES.index(current) if current in DIFFICULTIES else 1
    if qualities and qualities[-1] == "strong":
        i = min(i + 1, len(DIFFICULTIES) - 1)
    elif len(qualities) >= 2 and qualities[-1] == "weak" and qualities[-2] == "weak":
        i = max(i - 1, 0)
    return DIFFICULTIES[i]


def follow_ups_on_current_topic(messages: list[Message]) -> int:
    count = 0
    for m in reversed(messages):
        if m.speaker != "interviewer" or m.kind == "redirect":
            continue
        if m.kind == "follow_up":
            count += 1
        else:
            break
    return count


def cv_due(session: InterviewSession, messages: list[Message], next_number: int) -> CvDue:
    if not session.cv_text.strip():
        return "no_cv"
    if any(m.about_cv for m in messages if m.speaker == "interviewer"):
        return "done"
    if next_number >= min(CV_QUESTION_BY, session.question_limit):
        return "now"
    return "soon"


def plan_next(session: InterviewSession, messages: list[Message]) -> TurnPlan:
    number = session.questions_asked + 1
    next_round = round_for(session.session_type, session.question_limit, number)
    last_q = next((m for m in reversed(messages) if m.speaker == "interviewer" and m.kind != "redirect"), None)
    round_changed = last_q is not None and last_q.round != next_round
    follow_ups = follow_ups_on_current_topic(messages)
    answers = [m for m in messages if m.kind == "answer"]
    return TurnPlan(
        questions_asked=session.questions_asked,
        question_limit=session.question_limit,
        round=next_round,
        difficulty=session.difficulty if session.difficulty in DIFFICULTIES else "medium",  # type: ignore[arg-type]
        follow_ups_on_topic=follow_ups,
        follow_up_allowed=not round_changed and follow_ups < MAX_FOLLOW_UPS_PER_TOPIC,
        round_changed=round_changed,
        cv_due=cv_due(session, messages, number),
        previous_quality=answers[-1].quality if answers else None,
    )


# ---------- helpers ----------

def context_of(session: InterviewSession) -> InterviewContext:
    return InterviewContext(
        role=session.role,
        level=session.level,
        job_description=session.job_description,
        cv_text=session.cv_text,
        personality=session.personality,
        session_type=session.session_type,
    )


def record_usage(db: Session, session_id: str | None, usage: LLMUsage, ok: bool = True) -> None:
    db.add(
        LlmCall(
            session_id=session_id,
            agent=usage.agent,
            prompt=usage.prompt,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            latency_ms=usage.latency_ms,
            cost_usd=usage.cost_usd,
            ok=ok,
        )
    )
    if session_id is not None:
        session = db.get(InterviewSession, session_id)
        if session is not None:
            session.total_tokens += usage.total_tokens
            session.cost_usd = round(session.cost_usd + usage.cost_usd, 6)


def _record_failure(db: Session, session_id: str | None, err: LLMError) -> None:
    """Billed-but-failed calls (refusals, truncation) are still logged so cost stays accurate."""
    if err.usage is None:
        return
    record_usage(db, session_id, err.usage, ok=False)
    db.commit()


def _interviewer_message(turn: InterviewerTurn, plan: TurnPlan, has_cv: bool) -> Message:
    return Message(
        speaker="interviewer",
        kind=INTERVIEWER_KINDS[turn.decision],
        round=plan.round,
        topic=turn.topic[:100],
        difficulty=turn.difficulty,
        about_cv=turn.about_cv_project and has_cv,
        text=turn.question.strip(),
    )


def _transcript(messages: list[Message]) -> list[Turn]:
    return [Turn(m.speaker, m.text) for m in messages if m.kind != "closing"]  # type: ignore[arg-type]


def question_for(session: InterviewSession, answer: Message) -> Message:
    previous = [m for m in session.messages if m.speaker == "interviewer" and m.kind != "hint" and m.id < answer.id]
    return previous[-1]


# ---------- interview flow ----------

def start_session(
    db: Session,
    llm: LLM,
    *,
    user_id: int | None,
    role: str,
    level: str,
    job_description: str,
    question_limit: int,
    session_type: str = "full",
    personality: str = "friendly_hr",
    cv_id: int | None = None,
    cv_text: str = "",
) -> tuple[InterviewSession, Message]:
    session = InterviewSession(
        user_id=user_id,
        role=role,
        level=level,
        job_description=job_description,
        question_limit=question_limit,
        session_type=session_type,
        personality=personality,
        cv_id=cv_id,
        cv_text=cv_text,
        difficulty="medium",
        questions_asked=0,
    )
    plan = plan_next(session, [])
    try:
        result = interviewer.next_turn(llm, context_of(session), [], plan)
    except LLMError as err:
        _record_failure(db, None, err)
        raise

    first = _interviewer_message(result.output, plan, bool(cv_text.strip()))
    first.kind = "question"  # the opening is always a new question
    session.messages.append(first)
    session.questions_asked = 1
    db.add(session)
    db.flush()
    record_usage(db, session.id, result.usage)
    db.commit()
    return session, first


def _apply_voice(answer: Message, text: str, voice: VoiceInput | None) -> None:
    if voice is None:
        return
    m = speech_metrics.analyse(voice.transcript or text, voice.seconds)
    answer.is_voice = True
    answer.speech_seconds = voice.seconds
    answer.wpm = m.wpm
    answer.filler_count = m.filler_count
    answer.filler_words = m.filler_words


def submit_answer(
    db: Session, llm: LLM, session: InterviewSession, text: str, voice: VoiceInput | None = None
) -> tuple[Message, bool, int | None]:
    """Store the answer and produce the next interviewer message.

    Returns (interviewer_message, interview_done, answer_id_to_evaluate). If Claude fails, nothing is
    saved, so the candidate can simply resubmit the same answer.
    """
    if session.status != "active":
        raise SessionStateError("This interview has already ended.")
    if session.session_type == "coding" and not coding.submitted(session):
        raise SessionStateError("Submit your code first - then I'll ask you about it.")

    history = list(session.messages)
    asked_last = next(m for m in reversed(history) if m.speaker == "interviewer" and m.kind != "hint")
    answer = Message(speaker="candidate", kind="answer", round=asked_last.round, topic=asked_last.topic, text=text)
    _apply_voice(answer, text, voice)

    if session.questions_asked >= session.question_limit:
        session.messages.append(answer)
        closing = Message(speaker="interviewer", kind="closing", round=asked_last.round, text=CLOSING_TEXT)
        session.messages.append(closing)
        db.commit()
        return closing, True, answer.id

    plan = plan_next(session, history)
    try:
        result: LLMResult[InterviewerTurn] = interviewer.next_turn(
            llm, context_of(session), _transcript(history) + [Turn("candidate", text)], plan
        )
    except LLMError as err:
        db.rollback()
        _record_failure(db, session.id, err)
        raise

    turn = result.output
    reply = _interviewer_message(turn, plan, bool(session.cv_text.strip()))
    if reply.kind == "redirect":
        answer.kind = "off_topic"
        reply.round, reply.topic = asked_last.round, asked_last.topic  # restates the current question
    else:
        quality = turn.previous_answer_quality if turn.previous_answer_quality != "none" else None
        answer.quality = quality
        previous = [m.quality for m in history if m.kind == "answer"]
        session.difficulty = adjust_difficulty(session.difficulty, previous + [quality])
        session.questions_asked += 1
    session.messages.append(answer)
    session.messages.append(reply)
    record_usage(db, session.id, result.usage)
    db.commit()
    return reply, False, answer.id if answer.kind == "answer" else None


# ---------- evaluation ----------

def _store_evaluation(
    db: Session, session: InterviewSession, answer: Message, result: LLMResult[AnswerScore]
) -> None:
    score = result.output
    try:
        with db.begin_nested():
            db.add(
                Evaluation(
                    session_id=session.id,
                    message_id=answer.id,
                    topic=answer.topic,
                    correctness=score.correctness,
                    clarity=score.clarity,
                    depth=score.depth,
                    star_flags=score.star.model_dump() if answer.round == "hr" else None,  # FR-42
                    feedback=score.feedback,
                    model_answer=score.model_answer,
                )
            )
    except IntegrityError:  # already evaluated by a concurrent background task
        log.info("evaluation for message %s already exists", answer.id)
    record_usage(db, session.id, result.usage)
    db.commit()


ScoreJob = Callable[[LLM], LLMResult[AnswerScore]]


def score_job(session: InterviewSession, answer: Message) -> ScoreJob:
    """Collect everything needed to score one answer as plain data, so the LLM call can run on any thread."""
    ctx = context_of(session)
    if answer.kind == "code":
        facts = coding.submission_facts(session)
        assert facts is not None
        return lambda llm: coding.score_submission(llm, ctx, facts)
    question, text, rnd, spoken = question_for(session, answer).text, answer.text, answer.round, answer.is_voice
    extra = coding.complexity_context(coding.submission_facts(session)) if rnd == "coding" else []
    return lambda llm: evaluator.score_answer(llm, ctx, question, text, rnd, spoken=spoken, extra=extra)


def evaluate_in_background(llm: LLM, session_id: str, answer_id: int) -> None:
    """Score one answer right after it is given, so the final report is fast (NFR-02)."""
    with database.SessionLocal() as db:
        session = db.get(InterviewSession, session_id)
        answer = db.get(Message, answer_id)
        if session is None or answer is None:
            return
        exists = db.scalar(select(Evaluation.id).where(Evaluation.message_id == answer_id))
        if exists:
            return
        try:
            result = score_job(session, answer)(llm)
        except LLMError as err:
            log.warning("background evaluation failed for message %s; will retry at end: %s", answer_id, err)
            _record_failure(db, session_id, err)
            return
        _store_evaluation(db, session, answer, result)


def end_session(db: Session, llm: LLM, session: InterviewSession) -> Report:
    """Close the session, score any unscored answers and build the report. Safe to call again."""
    if session.report is not None:
        return session.report

    if session.status != "completed":
        session.status = "completed"
        session.ended_at = datetime.now(UTC)
        db.commit()

    ctx = context_of(session)
    answers = [m for m in session.messages if m.kind in SCORED_KINDS]
    done_ids = {e.message_id for e in session.evaluations}
    missing = [(a, score_job(session, a)) for a in answers if a.id not in done_ids]

    if missing:
        def work(item: tuple[Message, ScoreJob]):
            answer, job = item
            try:
                return answer, job(llm)
            except LLMError as err:
                return answer, err

        with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as pool:
            outcomes = list(pool.map(work, missing))  # LLM calls only; DB work stays on this thread

        first_error: LLMError | None = None
        for answer, outcome in outcomes:
            if isinstance(outcome, LLMError):
                _record_failure(db, session.id, outcome)
                first_error = first_error or outcome
            else:
                _store_evaluation(db, session, answer, outcome)
        if first_error:
            raise first_error
        db.refresh(session)

    evaluations = list(session.evaluations)
    by_id = {m.id: m for m in session.messages}
    if not evaluations:
        report = Report(
            session_id=session.id, overall_score=0.0, strengths=[], weaknesses=[], recommendation=NO_ANSWERS_TEXT
        )
    else:
        items = [
            ScoredItem(e.topic or "", by_id[e.message_id].round, e.correctness, e.clarity, e.depth, e.feedback)
            for e in evaluations
        ]
        try:
            result = evaluator.summarize(llm, ctx, items)
        except LLMError as err:
            _record_failure(db, session.id, err)
            raise
        record_usage(db, session.id, result.usage)
        overall = round(sum(e.average for e in evaluations) / len(evaluations), 1)
        report = Report(
            session_id=session.id,
            overall_score=overall,
            strengths=result.output.strengths,
            weaknesses=result.output.weaknesses,
            recommendation=result.output.summary,
        )

    db.add(report)
    db.commit()
    db.refresh(session)
    return report
