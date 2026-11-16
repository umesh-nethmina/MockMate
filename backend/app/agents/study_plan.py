"""Study-plan agent (FR-53): turns one report plus the candidate's history of weak topics into a short,
concrete plan. Runs only when the candidate asks for it, so ordinary sessions don't pay for it."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.context import InterviewContext, tag
from app.agents.evaluator import ScoredItem
from app.config import get_settings
from app.llm import LLM, LLMResult

PROMPT = "study_plan.v1"


class StudyItem(BaseModel):
    topic: str
    priority: Literal["high", "medium", "low"]
    why: str = Field(description="One sentence linking this to the candidate's answers")
    actions: list[str] = Field(description="2-4 concrete things to do")
    practice_question: str = Field(description="An interview question to practise answering")
    hours: int = Field(description="Rough hours needed, 1-10")


class StudyPlan(BaseModel):
    summary: str
    items: list[StudyItem]
    next_session: str = Field(description="Suggested setup for the next mock interview")


def create(
    llm: LLM, ctx: InterviewContext, items: list[ScoredItem], history: list[dict]
) -> LLMResult[StudyPlan]:
    session_data = json.dumps([i.__dict__ for i in items], indent=1, ensure_ascii=False)
    history_data = json.dumps(history, indent=1, ensure_ascii=False, default=str)
    content = "\n\n".join(
        [
            f"Target role: {ctx.role}\nLevel: {ctx.level}\nInterview type: {ctx.session_type}",
            tag("job_description", ctx.job_description.strip() or "(none provided)"),
            tag("this_session", session_data),
            tag("weak_topics_history", history_data),
        ]
    )
    result = llm.structured(
        agent="study_plan",
        prompt=PROMPT,
        messages=[{"role": "user", "content": content}],
        output_model=StudyPlan,
        effort=get_settings().report_effort,
    )
    plan = result.output
    order = {"high": 0, "medium": 1, "low": 2}
    plan.items = sorted(plan.items, key=lambda i: order[i.priority])[:5]
    for item in plan.items:
        item.hours = max(1, min(10, item.hours))
        item.actions = item.actions[:4]
    return result
