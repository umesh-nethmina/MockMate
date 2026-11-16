"""Evaluator agent: scores each answer (FR-40) and writes the report summary (FR-41)."""

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.agents.context import InterviewContext, tag
from app.config import get_settings
from app.llm import LLM, LLMResult

ANSWER_PROMPT = "evaluator.v1"
REPORT_PROMPT = "report.v1"


class AnswerScore(BaseModel):
    correctness: int = Field(description="1-10")
    clarity: int = Field(description="1-10")
    depth: int = Field(description="1-10")
    feedback: str
    model_answer: str

    def clamped(self) -> "AnswerScore":
        def c(v: int) -> int:
            return max(1, min(10, int(v)))

        return self.model_copy(
            update={"correctness": c(self.correctness), "clarity": c(self.clarity), "depth": c(self.depth)}
        )


class ReportSummary(BaseModel):
    strengths: list[str]
    weaknesses: list[str]
    summary: str


@dataclass(frozen=True)
class ScoredItem:
    topic: str
    correctness: int
    clarity: int
    depth: int
    feedback: str


def score_answer(llm: LLM, ctx: InterviewContext, question: str, answer: str) -> LLMResult[AnswerScore]:
    content = "\n\n".join([ctx.as_prompt(), tag("question", question), tag("candidate_answer", answer)])
    result = llm.structured(
        agent="evaluator",
        prompt=ANSWER_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_model=AnswerScore,
        effort=get_settings().evaluator_effort,
    )
    result.output = result.output.clamped()
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
