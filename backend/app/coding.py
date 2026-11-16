"""Coding round (FR-30..FR-34, FR-60): problem choice, sandbox runs, hints, submission and scoring.

Plain Python state logic like the orchestrator: hints and the complexity follow-up are pre-written, so the
only Claude call in a coding session is the final code review.
"""

import json
import keyword
import random
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import evaluator
from app.agents.context import InterviewContext
from app.agents.evaluator import AnswerScore, StarFlags
from app.config import get_settings
from app.llm import LLM, LLMResult
from app.models import CodeRun, CodingProblem, InterviewSession, Message
from app.tools.sandbox import Language, RunResult, Sandbox

LEVEL_DIFFICULTIES = {"intern": ["easy"], "junior": ["easy", "medium"], "mid": ["medium", "hard"]}
CODING_QUESTION_LIMIT = 2  # the problem itself, then the complexity follow-up (FR-34)
SEED_FILE = Path(__file__).parent / "data" / "problems.json"

INTRO_TEXT = (
    "Let's do a coding exercise: {title}. The problem and the sample tests are next to the editor. "
    "Run your code as often as you like, and ask for a hint if you get stuck (each hint costs a little). "
    "Submit when you're happy - your code is then checked against hidden tests too, and I'll ask you about it."
)
COMPLEXITY_QUESTION = (
    "Thanks for submitting. What are the time and space complexity of your solution, and why? "
    "Could it be made faster or use less memory, and what would that cost?"
)
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class CodingStateError(Exception):
    """The coding request does not fit the session's state (HTTP 409)."""


class RunLimitReached(Exception):
    """Too many sandbox runs in one session (HTTP 429)."""


# ---------- problems ----------

def js_name(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


def function_for(problem: CodingProblem, language: Language) -> str:
    return js_name(problem.function_name) if language == "javascript" else problem.function_name


def starter_code(problem: CodingProblem, language: Language) -> str:
    if language == "javascript":
        args = ", ".join(js_name(p) for p in problem.params)
        return f"function {js_name(problem.function_name)}({args}) {{\n  // your code here\n}}\n"
    return f"def {problem.function_name}({', '.join(problem.params)}):\n    # your code here\n    pass\n"


def visible_tests(problem: CodingProblem) -> list[dict]:
    return [t for t in problem.tests if not t.get("hidden")]


def check_problem_shape(function_name: str, params: list[str], tests: list[dict]) -> list[str]:
    """Static checks before the reference solution is run (UC-05)."""
    errors = []
    for name in [function_name, *params]:
        if not _IDENTIFIER.match(name) or keyword.iskeyword(name):
            errors.append(f"'{name}' is not a valid snake_case Python name")
    if not any(not t.get("hidden") for t in tests):
        errors.append("Add at least one sample (visible) test")
    if not any(t.get("hidden") for t in tests):
        errors.append("Add at least one hidden test")
    for i, t in enumerate(tests, 1):
        if len(t.get("args", [])) != len(params):
            errors.append(f"Test {i} has {len(t.get('args', []))} arguments but the function takes {len(params)}")
    return errors


def validate_reference(sandbox: Sandbox, function_name: str, reference: str, tests: list[dict]) -> list[str]:
    """UC-05: the reference solution must pass every test, or the problem is not saved."""
    result = sandbox.run("python", reference, function_name, [_payload(t) for t in tests])
    if result.status != "ok":
        return [f"Reference solution failed to run: {result.message}"]
    errors = []
    for i, (test, outcome) in enumerate(zip(tests, result.results, strict=True), 1):
        if not outcome.ok:
            got = outcome.error or json.dumps(outcome.output)
            errors.append(f"Test {i}: expected {json.dumps(test['expected'])}, reference solution gave {got}")
    return errors


def pick_problem(db: Session, user_id: int, level: str) -> CodingProblem | None:
    """A problem at the candidate's level, preferring ones they have not seen before."""
    difficulties = LEVEL_DIFFICULTIES.get(level, ["easy", "medium"])
    candidates = list(
        db.scalars(
            select(CodingProblem).where(CodingProblem.is_active, CodingProblem.difficulty.in_(difficulties))
        )
    ) or list(db.scalars(select(CodingProblem).where(CodingProblem.is_active)))
    if not candidates:
        return None
    seen = set(
        db.scalars(
            select(InterviewSession.problem_id).where(
                InterviewSession.user_id == user_id, InterviewSession.problem_id.is_not(None)
            )
        )
    )
    fresh = [p for p in candidates if p.id not in seen]
    return random.choice(fresh or candidates)


def seed_problems(db: Session) -> int:
    """Load the starter problem bank into an empty table (first start-up)."""
    if db.scalar(select(func.count()).select_from(CodingProblem)):
        return 0
    problems = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    for p in problems:
        db.add(CodingProblem(**p))
    db.commit()
    return len(problems)


# ---------- session flow ----------

def start_coding_session(
    db: Session, *, user_id: int, problem: CodingProblem, role: str, level: str, job_description: str,
    personality: str,
) -> tuple[InterviewSession, Message]:
    session = InterviewSession(
        user_id=user_id,
        role=role,
        level=level,
        job_description=job_description,
        session_type="coding",
        personality=personality,
        question_limit=CODING_QUESTION_LIMIT,
        questions_asked=1,
        difficulty=problem.difficulty if problem.difficulty in ("easy", "medium", "hard") else "medium",
        problem_id=problem.id,
    )
    intro = Message(
        speaker="interviewer",
        kind="question",
        round="coding",
        topic=problem.topic[:100],
        difficulty=problem.difficulty,
        text=INTRO_TEXT.format(title=problem.title),
    )
    session.messages.append(intro)
    db.add(session)
    db.commit()
    return session, intro


def submitted(session: InterviewSession) -> bool:
    return any(m.kind == "code" for m in session.messages)


def _require_open(session: InterviewSession) -> CodingProblem:
    if session.session_type != "coding" or session.problem is None:
        raise CodingStateError("This interview has no coding exercise.")
    if session.status != "active":
        raise CodingStateError("This interview has already ended.")
    if submitted(session):
        raise CodingStateError("Your code has already been submitted.")
    return session.problem


def _payload(test: dict) -> dict:
    return {"args": test["args"], "expected": test["expected"]}


def run_code(
    db: Session, sandbox: Sandbox, session: InterviewSession, language: Language, code: str, *, submit: bool
) -> CodeRun:
    """Run against the sample tests (run) or all tests (submit). Hidden tests' inputs are never returned (FR-32)."""
    problem = _require_open(session)
    runs = db.scalar(select(func.count()).where(CodeRun.session_id == session.id)) or 0
    if runs >= get_settings().max_code_runs_per_session:
        raise RunLimitReached()

    samples = visible_tests(problem)
    hidden = [t for t in problem.tests if t.get("hidden")] if submit else []
    tests = samples + hidden
    result: RunResult = sandbox.run(language, code, function_for(problem, language), [_payload(t) for t in tests])

    rows = []
    for i, test in enumerate(tests):
        outcome = result.results[i] if i < len(result.results) else None
        if test.get("hidden"):
            rows.append({"hidden": True, "ok": bool(outcome and outcome.ok),
                         "error": _short_error(outcome.error) if outcome else None})
        else:
            rows.append({
                "hidden": False,
                "args": test["args"],
                "expected": test["expected"],
                "ok": bool(outcome and outcome.ok),
                "output": outcome.output if outcome else None,
                "stdout": outcome.stdout if outcome else "",
                "error": outcome.error if outcome else None,
                "ms": outcome.ms if outcome else None,
            })
    sample_rows = [r for r in rows if not r["hidden"]]
    hidden_rows = [r for r in rows if r["hidden"]]
    run = CodeRun(
        session_id=session.id,
        kind="submit" if submit else "run",
        language=language,
        code=code,
        status=result.status,
        message=result.message,
        passed=sum(r["ok"] for r in sample_rows),
        total=len(sample_rows),
        hidden_passed=sum(r["ok"] for r in hidden_rows),
        hidden_total=len(hidden_rows),
        results=rows,
        duration_ms=result.duration_ms,
    )
    db.add(run)
    if submit:
        session.messages.append(
            Message(speaker="candidate", kind="code", round="coding", topic=problem.topic[:100], text=code)
        )
        session.messages.append(
            Message(
                speaker="interviewer", kind="follow_up", round="coding", topic=problem.topic[:100],
                difficulty=problem.difficulty, text=COMPLEXITY_QUESTION,
            )
        )
        session.questions_asked = CODING_QUESTION_LIMIT
    db.commit()
    return run


def _short_error(error: str | None) -> str | None:
    """For hidden tests, only the kind of failure (e.g. 'IndexError'), never details that leak the input."""
    if not error:
        return None
    if error.startswith(("Time limit", "Not run")):
        return error
    return error.split(":", 1)[0][:60]


def next_hint(db: Session, session: InterviewSession) -> Message:
    """FR-33: reveal the next pre-written hint; each one lowers the correctness score by a point."""
    problem = _require_open(session)
    if session.hints_used >= len(problem.hints):
        raise CodingStateError("There are no more hints for this problem.")
    session.hints_used += 1
    hint = Message(
        speaker="interviewer",
        kind="hint",
        round="coding",
        topic=problem.topic[:100],
        text=f"Hint {session.hints_used} of {len(problem.hints)}: {problem.hints[session.hints_used - 1]}",
    )
    session.messages.append(hint)
    db.commit()
    return hint


def last_submission(session: InterviewSession) -> CodeRun | None:
    return next((r for r in reversed(session.code_runs) if r.kind == "submit"), None)


# ---------- scoring ----------

def correctness_score(run: CodeRun, hints_used: int) -> int:
    """Deterministic: share of all tests passed mapped to 1-10, minus one point per hint used."""
    total = run.total + run.hidden_total
    ratio = (run.passed + run.hidden_passed) / total if total and run.status == "ok" else 0.0
    return max(1, round(1 + 9 * ratio) - hints_used)


@dataclass(frozen=True)
class SubmissionFacts:
    """Plain data captured on the request thread, so scoring can run in a worker thread."""

    title: str
    statement: str
    expected_complexity: str
    language: str
    code: str
    status: str
    message: str | None
    passed: int
    total: int
    hints_used: int
    hints_total: int
    correctness: int


def submission_facts(session: InterviewSession) -> SubmissionFacts | None:
    run, problem = last_submission(session), session.problem
    if run is None:
        return None
    return SubmissionFacts(
        title=problem.title if problem else "Coding exercise",
        statement=problem.statement if problem else "",
        expected_complexity=problem.expected_complexity if problem else "",
        language=run.language,
        code=run.code,
        status=run.status,
        message=run.message,
        passed=run.passed + run.hidden_passed,
        total=run.total + run.hidden_total,
        hints_used=session.hints_used,
        hints_total=len(problem.hints) if problem else 0,
        correctness=correctness_score(run, session.hints_used),
    )


def score_submission(llm: LLM, ctx: InterviewContext, facts: SubmissionFacts) -> LLMResult[AnswerScore]:
    """Claude reviews code quality and efficiency; correctness comes from the tests, not the model."""
    result = evaluator.review_code(
        llm,
        ctx,
        title=facts.title,
        statement=facts.statement,
        expected_complexity=facts.expected_complexity,
        language=facts.language,
        code=facts.code,
        test_summary=_test_summary(facts),
        hints=f"{facts.hints_used} of {facts.hints_total}",
    )
    review = result.output
    score = AnswerScore(
        correctness=facts.correctness,
        clarity=review.code_quality,
        depth=review.efficiency,
        star=StarFlags(situation=False, task=False, action=False, result=False),
        feedback=review.feedback,
        model_answer=review.model_answer,
    ).clamped()
    return LLMResult(score, result.usage)


def _test_summary(facts: SubmissionFacts) -> str:
    if facts.status == "ok":
        return f"{facts.passed} of {facts.total} tests passed"
    return f"The code did not run to completion ({facts.status}): {facts.message or ''}".strip()


def complexity_context(facts: SubmissionFacts | None) -> list[tuple[str, str]]:
    """Extra evaluator context for the complexity follow-up answer: the code it is about."""
    if facts is None:
        return []
    return [
        ("problem", f"{facts.title}\n{facts.statement}"),
        ("candidate_code", facts.code),
        ("reference_complexity", facts.expected_complexity),
    ]
