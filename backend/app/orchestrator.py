"""Orchestrator: deterministic session state machine. It routes each turn to the right agent,
enforces question limits (FR-14) and saves state after every turn (NFR-12). It never calls Claude itself."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db as database
from app.agents import evaluator, interviewer
from app.agents.context import InterviewContext
from app.agents.evaluator import AnswerScore, ScoredItem
from app.agents.interviewer import InterviewerTurn, Turn
from app.llm import LLM, LLMError, LLMResult, LLMUsage
from app.models import Evaluation, InterviewSession, LlmCall, Message, Report

log = logging.getLogger(__name__)

CLOSING_TEXT = "That's the end of our interview - thank you for your time! I'm preparing your report now."
INTERVIEWER_KINDS = {"follow_up": "follow_up", "next_topic": "question", "redirect": "redirect"}
EVAL_WORKERS = 4
NO_ANSWERS_TEXT = "No answers were given, so there is nothing to score yet. Start a new interview to get feedback."


class SessionStateError(Exception):
    """The request does not fit the session's current state (HTTP 409)."""


# ---------- helpers ----------

def context_of(session: InterviewSession) -> InterviewContext:
    return InterviewContext(session.role, session.level, session.job_description)


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


def _interviewer_message(turn: InterviewerTurn) -> Message:
    return Message(
        speaker="interviewer",
        kind=INTERVIEWER_KINDS[turn.decision],
        round=turn.round,
        topic=turn.topic[:100],
        difficulty=turn.difficulty,
        text=turn.question.strip(),
    )


def _transcript(messages: list[Message]) -> list[Turn]:
    return [Turn(m.speaker, m.text) for m in messages if m.kind != "closing"]  # type: ignore[arg-type]


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


def question_for(session: InterviewSession, answer: Message) -> Message:
    previous = [m for m in session.messages if m.speaker == "interviewer" and m.id < answer.id]
    return previous[-1]


# ---------- interview flow ----------

def start_session(
    db: Session,
    llm: LLM,
    *,
    role: str,
    level: str,
    job_description: str,
    question_limit: int,
) -> tuple[InterviewSession, Message]:
    session = InterviewSession(
        role=role, level=level, job_description=job_description, question_limit=question_limit
    )
    try:
        result = interviewer.next_turn(
            llm, context_of(session), [], questions_asked=0, question_limit=question_limit, follow_ups_on_topic=0
        )
    except LLMError as err:
        _record_failure(db, None, err)
        raise

    first = _interviewer_message(result.output)
    first.kind = "question"  # the opening is always a new question
    session.messages.append(first)
    session.questions_asked = 1
    db.add(session)
    db.flush()
    record_usage(db, session.id, result.usage)
    db.commit()
    return session, first


def submit_answer(db: Session, llm: LLM, session: InterviewSession, text: str) -> tuple[Message, bool, int | None]:
    """Store the answer and produce the next interviewer message.

    Returns (interviewer_message, interview_done, answer_id_to_evaluate). If Claude fails, nothing is
    saved, so the candidate can simply resubmit the same answer.
    """
    if session.status != "active":
        raise SessionStateError("This interview has already ended.")

    history = list(session.messages)
    asked_last = next(m for m in reversed(history) if m.speaker == "interviewer")
    answer = Message(speaker="candidate", kind="answer", round=asked_last.round, topic=asked_last.topic, text=text)

    if session.questions_asked >= session.question_limit:
        session.messages.append(answer)
        closing = Message(speaker="interviewer", kind="closing", round=asked_last.round, text=CLOSING_TEXT)
        session.messages.append(closing)
        db.commit()
        return closing, True, answer.id

    try:
        result: LLMResult[InterviewerTurn] = interviewer.next_turn(
            llm,
            context_of(session),
            _transcript(history) + [Turn("candidate", text)],
            questions_asked=session.questions_asked,
            question_limit=session.question_limit,
            follow_ups_on_topic=follow_ups_on_current_topic(history),
        )
    except LLMError as err:
        db.rollback()
        _record_failure(db, session.id, err)
        raise

    reply = _interviewer_message(result.output)
    if reply.kind == "redirect":
        answer.kind = "off_topic"
    else:
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
                    feedback=score.feedback,
                    model_answer=score.model_answer,
                )
            )
    except IntegrityError:  # already evaluated by a concurrent background task
        log.info("evaluation for message %s already exists", answer.id)
    record_usage(db, session.id, result.usage)
    db.commit()


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
        question = question_for(session, answer)
        try:
            result = evaluator.score_answer(llm, context_of(session), question.text, answer.text)
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
    answers = [m for m in session.messages if m.kind == "answer"]
    done_ids = {e.message_id for e in session.evaluations}
    missing = [(a, question_for(session, a).text) for a in answers if a.id not in done_ids]

    if missing:
        def work(item: tuple[Message, str]):
            answer, question = item
            try:
                return answer, evaluator.score_answer(llm, ctx, question, answer.text)
            except LLMError as err:
                return answer, err

        with ThreadPoolExecutor(max_workers=EVAL_WORKERS) as pool:
            outcomes = list(pool.map(work, [(a, q) for a, q in missing]))  # LLM calls only; DB stays on this thread

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
    if not evaluations:
        report = Report(
            session_id=session.id,
            overall_score=0.0,
            strengths=[],
            weaknesses=[],
            recommendation=NO_ANSWERS_TEXT,
        )
    else:
        items = [ScoredItem(e.topic or "", e.correctness, e.clarity, e.depth, e.feedback) for e in evaluations]
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
