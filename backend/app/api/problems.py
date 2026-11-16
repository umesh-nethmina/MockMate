"""Admin management of coding problems (FR-60, UC-05). A problem is only saved when its reference solution
passes every one of its tests in the sandbox."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import coding
from app.auth import require_admin
from app.db import get_db
from app.models import CodingProblem, InterviewSession
from app.tools.sandbox import Sandbox, get_sandbox

router = APIRouter(prefix="/admin/problems", tags=["admin"], dependencies=[Depends(require_admin)])

Text = Annotated[str, StringConstraints(strip_whitespace=True)]


class TestCase(BaseModel):
    args: list[Any]
    expected: Any
    hidden: bool = False


class ProblemIn(BaseModel):
    title: Annotated[Text, StringConstraints(min_length=3, max_length=120)]
    difficulty: Literal["easy", "medium", "hard"]
    topic: Annotated[Text, StringConstraints(min_length=2, max_length=100)]
    statement: Annotated[Text, StringConstraints(min_length=10, max_length=5000)]
    function_name: Annotated[Text, StringConstraints(min_length=1, max_length=60)]
    params: list[Annotated[Text, StringConstraints(min_length=1, max_length=40)]] = Field(max_length=6)
    tests: list[TestCase] = Field(min_length=2, max_length=30)
    hints: list[Annotated[Text, StringConstraints(min_length=1, max_length=500)]] = Field(default=[], max_length=5)
    reference_solution: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    expected_complexity: Annotated[Text, StringConstraints(max_length=200)] = ""
    is_active: bool = True


class ProblemOut(ProblemIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    times_used: int = 0


def _validate(body: ProblemIn, sandbox: Sandbox) -> None:
    tests = [t.model_dump() for t in body.tests]
    errors = coding.check_problem_shape(body.function_name, body.params, tests)
    if not errors:
        errors = coding.validate_reference(sandbox, body.function_name, body.reference_solution, tests)
    if errors:
        raise HTTPException(422, "; ".join(errors[:5]))


def _out(db: Session, p: CodingProblem) -> ProblemOut:
    used = db.scalar(select(func.count()).where(InterviewSession.problem_id == p.id)) or 0
    return ProblemOut.model_validate(p).model_copy(update={"times_used": used})


def _get(db: Session, problem_id: int) -> CodingProblem:
    p = db.get(CodingProblem, problem_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found")
    return p


@router.get("")
def list_problems(db: Session = Depends(get_db)) -> list[ProblemOut]:
    return [_out(db, p) for p in db.scalars(select(CodingProblem).order_by(CodingProblem.id))]


@router.get("/{problem_id}")
def get_problem(problem_id: int, db: Session = Depends(get_db)) -> ProblemOut:
    return _out(db, _get(db, problem_id))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_problem(
    body: ProblemIn, db: Session = Depends(get_db), sandbox: Sandbox = Depends(get_sandbox)
) -> ProblemOut:
    _validate(body, sandbox)
    data = body.model_dump()
    data["tests"] = [t.model_dump() for t in body.tests]
    p = CodingProblem(**data)
    db.add(p)
    db.commit()
    return _out(db, p)


@router.put("/{problem_id}")
def update_problem(
    problem_id: int, body: ProblemIn, db: Session = Depends(get_db), sandbox: Sandbox = Depends(get_sandbox)
) -> ProblemOut:
    p = _get(db, problem_id)
    _validate(body, sandbox)
    for key, value in body.model_dump().items():
        setattr(p, key, value)
    p.tests = [t.model_dump() for t in body.tests]
    db.commit()
    return _out(db, p)


@router.delete("/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_problem(problem_id: int, db: Session = Depends(get_db)) -> Response:
    """Archive rather than delete: past sessions and reports still refer to the problem."""
    p = _get(db, problem_id)
    p.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
