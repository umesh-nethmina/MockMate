"""Evaluator agent: scores each answer (FR-40), checks STAR (FR-42), reviews submitted code (FR-34) and writes the
report summary (FR-41)."""

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.context import InterviewContext, tag
from app.config import get_settings
from app.llm import LLM, LLMResult

ANSWER_PROMPT = "evaluator.v3"
CODE_PROMPT = "code_review.v1"
REPORT_PROMPT = "report.v1"


class StarFlags(BaseModel):
    situation: bool
    task: bool
    action: bool
    result: bool


class AnswerScore(BaseModel):
    correctness: int = Field(description="1-10")
    clarity: int = Field(description="1-10")
    depth: int = Field(description="1-10")
    star: StarFlags
    feedback: str
    model_answer: str

    def clamped(self) -> "AnswerScore":
        def c(v: int) -> int:
            return max(1, min(10, int(v)))

        return self.model_copy(
            update={"correctness": c(self.correctness), "clarity": c(self.clarity), "depth": c(self.depth)}
        )


class CodeReview(BaseModel):
    code_quality: int = Field(description="1-10: readability, naming, structure, edge cases")
    efficiency: int = Field(description="1-10: algorithm choice and time/space complexity")
    feedback: str
    model_answer: str


class ReportSummary(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    summary: str


@dataclass(frozen=True)
class ScoredItem:
    topic: str
    round: str
    correctness: int
    clarity: int
    depth: int
    feedback: str


def score_answer(
    llm: LLM,
    ctx: InterviewContext,
    question: str,
    answer: str,
    round: str = "technical",
    spoken: bool = False,
    extra: list[tuple[str, str]] | None = None,
) -> LLMResult[AnswerScore]:
    """`extra` adds tagged context blocks, e.g. the candidate's code for a coding-round follow-up."""
    mode = "spoken (speech-to-text transcript)" if spoken else "typed"
    content = "\n\n".join(
        [
            ctx.as_prompt(include_style=False, include_cv=False),
            f"Round: {round}\nAnswer mode: {mode}",
            *(tag(name, text) for name, text in extra or []),
            tag("question", question),
            tag("candidate_answer", answer),
        ]
    )
    result = llm.structured(
        agent="evaluator",
        prompt=ANSWER_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_model=AnswerScore,
        effort=get_settings().evaluator_effort,
    )
    result.output = result.output.clamped()
    return result


def review_code(
    llm: LLM,
    ctx: InterviewContext,
    *,
    title: str,
    statement: str,
    expected_complexity: str,
    language: str,
    code: str,
    test_summary: str,
    hints: str,
) -> LLMResult[CodeReview]:
    content = "\n\n".join(
        [
            f"Target role: {ctx.role}\nLevel: {ctx.level}",
            tag("problem", f"{title}\n{statement}"),
            f"Reference complexity: {expected_complexity}\nLanguage: {language}\n"
            f"Test results: {test_summary}\nHints used: {hints}",
            tag("candidate_code", code),
        ]
    )
    result = llm.structured(
        agent="evaluator",
        prompt=CODE_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_model=CodeReview,
        effort=get_settings().evaluator_effort,
    )

    def c(v: int) -> int:
        return max(1, min(10, int(v)))

    out = result.output
    result.output = out.model_copy(update={"code_quality": c(out.code_quality), "efficiency": c(out.efficiency)})
    return result


def summarize(llm: LLM, ctx: InterviewContext, items: list[ScoredItem]) -> LLMResult[ReportSummary]:
    data = json.dumps([item.__dict__ for item in items], indent=1, ensure_ascii=False)
    content = (
        f"Target role: {ctx.role}\nLevel: {ctx.level}\n"
        f"Answers evaluated: {len(items)}\n\n{tag('evaluations', data)}"
    )
    return llm.structured(
        agent="report",
        prompt=REPORT_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_model=ReportSummary,
        effort=get_settings().report_effort,
    )
