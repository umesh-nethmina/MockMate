"""Coding round endpoints (FR-30..FR-34): problem, run (sample tests), hint and submit (all tests)."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from app import coding, orchestrator
from app.api.sessions import MessageOut, TurnResponse, get_owned_session
from app.db import get_db
from app.llm import LLM, get_llm
from app.models import CodeRun, InterviewSession
from app.tools.sandbox import Sandbox, get_sandbox

router = APIRouter(prefix="/sessions", tags=["coding"])

Code = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class CodeRequest(BaseModel):
    language: Literal["python", "javascript"]
    code: Code


class Sample(BaseModel):
    args: list[Any]
    expected: Any


class RunOut(BaseModel):
    id: int
    kind: str
    language: str
    code: str
    status: str
    message: str | None
    passed: int
    total: int
    hidden_passed: int
    hidden_total: int
    results: list[dict[str, Any]]
    duration_ms: int
    created_at: datetime


class ProblemOut(BaseModel):
    title: str
    difficulty: str
    topic: str
    statement: str
    function_names: dict[str, str]
    params: list[str]
    starter_code: dict[str, str]
    samples: list[Sample]
    hidden_tests: int
    hints_total: int
    hints_used: int
    submitted: bool
    last_run: RunOut | None


class HintOut(BaseModel):
    message: MessageOut
    hints_used: int
    hints_total: int


class SubmitOut(TurnResponse):
    run: RunOut


def run_out(run: CodeRun) -> RunOut:
    return RunOut(
        id=run.id,
        kind=run.kind,
        language=run.language,
        code=run.code,
        status=run.status,
        message=run.message,
        passed=run.passed,
        total=run.total,
        hidden_passed=run.hidden_passed,
        hidden_total=run.hidden_total,
        results=run.results,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
    )


def _problem(session: InterviewSession):
    if session.session_type != "coding" or session.problem is None:
        raise coding.CodingStateError("This interview has no coding exercise.")
    return session.problem


@router.get("/{session_id}/problem")
def get_problem(session: InterviewSession = Depends(get_owned_session)) -> ProblemOut:
    p = _problem(session)
    return ProblemOut(
        title=p.title,
        difficulty=p.difficulty,
        topic=p.topic,
        statement=p.statement,
        function_names={"python": p.function_name, "javascript": coding.js_name(p.function_name)},
        params=p.params,
        starter_code={lang: coding.starter_code(p, lang) for lang in ("python", "javascript")},
        samples=[Sample(args=t["args"], expected=t["expected"]) for t in coding.visible_tests(p)],
        hidden_tests=sum(1 for t in p.tests if t.get("hidden")),
        hints_total=len(p.hints),
        hints_used=session.hints_used,
        submitted=coding.submitted(session),
        last_run=run_out(session.code_runs[-1]) if session.code_runs else None,  # restores the editor (NFR-12)
    )


@router.post("/{session_id}/code/run")
def run_code(
    body: CodeRequest,
    session: InterviewSession = Depends(get_owned_session),
    db: Session = Depends(get_db),
    sandbox: Sandbox = Depends(get_sandbox),
) -> RunOut:
    """Run against the sample tests only (FR-31)."""
    return run_out(coding.run_code(db, sandbox, session, body.language, body.code, submit=False))


@router.post("/{session_id}/code/hint")
def hint(session: InterviewSession = Depends(get_owned_session), db: Session = Depends(get_db)) -> HintOut:
    message = coding.next_hint(db, session)
    return HintOut(
        message=MessageOut.model_validate(message),
        hints_used=session.hints_used,
        hints_total=len(_problem(session).hints),
    )


@router.post("/{session_id}/code/submit")
def submit_code(
    body: CodeRequest,
    background: BackgroundTasks,
    session: InterviewSession = Depends(get_owned_session),
    db: Session = Depends(get_db),
    sandbox: Sandbox = Depends(get_sandbox),
    llm: LLM = Depends(get_llm),
) -> SubmitOut:
    """Final submission against sample and hidden tests (FR-32), then the complexity follow-up (FR-34)."""
    run = coding.run_code(db, sandbox, session, body.language, body.code, submit=True)
    code_msg = next(m for m in reversed(session.messages) if m.kind == "code")
    follow_up = session.messages[-1]
    background.add_task(orchestrator.evaluate_in_background, llm, session.id, code_msg.id)
    return SubmitOut(
        session_id=session.id,
        message=MessageOut.model_validate(follow_up),
        done=False,
        questions_asked=session.questions_asked,
        question_limit=session.question_limit,
        run=run_out(run),
    )
