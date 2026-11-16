"""Interviewer agent: picks follow-up vs next topic and writes the next question
(FR-10, FR-11, FR-12, FR-13, FR-16). The orchestrator decides the plan; this agent follows it."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.context import InterviewContext
from app.config import get_settings
from app.llm import LLM, LLMResult

PROMPT = "interviewer.v2"
MAX_FOLLOW_UPS_PER_TOPIC = 2

Round = Literal["hr", "technical"]
Difficulty = Literal["easy", "medium", "hard"]
CvDue = Literal["no_cv", "done", "soon", "now"]


class InterviewerTurn(BaseModel):
    decision: Literal["follow_up", "next_topic", "redirect"]
    previous_answer_quality: Literal["strong", "adequate", "weak", "none"]
    round: Round
    topic: str = Field(description="2-4 word label for the skill or subject being tested")
    difficulty: Difficulty
    about_cv_project: bool
    question: str = Field(description="Exact words said to the candidate")


@dataclass(frozen=True)
class Turn:
    """One line of transcript as the interviewer sees it."""

    speaker: Literal["interviewer", "candidate"]
    text: str


@dataclass(frozen=True)
class TurnPlan:
    """What the orchestrator wants from the next question."""

    questions_asked: int
    question_limit: int
    round: Round
    difficulty: Difficulty
    follow_ups_on_topic: int = 0
    follow_up_allowed: bool = True
    round_changed: bool = False
    cv_due: CvDue = "no_cv"
    previous_quality: str | None = None  # your judgement of the answer before the latest one


def status_note(plan: TurnPlan) -> str:
    parts = []
    if plan.questions_asked == 0:
        parts.append(f"Start of the interview. Questions planned: {plan.question_limit}.")
    else:
        parts.append(f"Questions asked so far: {plan.questions_asked} of {plan.question_limit}.")
    parts.append(f"Round for the next question: {plan.round}. Target difficulty: {plan.difficulty}.")
    if plan.questions_asked:
        parts.append(f"You judged the answer before the latest one as: {plan.previous_quality or 'n/a'}.")
    if plan.round_changed:
        parts.append(f"The previous round is over: ask the first {plan.round} question with next_topic.")
    elif plan.questions_asked and not plan.follow_up_allowed:
        parts.append("No more follow-ups are allowed on the current topic: use next_topic or redirect.")
    elif plan.questions_asked:
        parts.append(
            f"Follow-ups already asked on the current topic: {plan.follow_ups_on_topic} "
            f"(max {MAX_FOLLOW_UPS_PER_TOPIC})."
        )
    if plan.cv_due == "soon":
        parts.append("You have not yet asked about a project from the CV: do so within the next two new questions.")
    elif plan.cv_due == "now":
        parts.append("Your next new question (not a follow-up) must be about a specific project named in the CV.")
    if plan.questions_asked == plan.question_limit - 1:
        parts.append("Your next question is the final question of the interview.")
    return " ".join(parts)


def build_messages(ctx: InterviewContext, transcript: list[Turn], note: str) -> list[dict]:
    """Real multi-turn history so the growing prefix is cache-friendly; the volatile status goes last."""
    messages: list[dict] = [{"role": "user", "content": ctx.as_prompt() + "\n\nPlease begin the interview."}]
    for turn in transcript:
        role = "assistant" if turn.speaker == "interviewer" else "user"
        messages.append({"role": role, "content": turn.text})
    last = messages[-1]
    last["content"] = [
        {"type": "text", "text": last["content"]},
        {"type": "text", "text": f"<status>{note}</status>"},
    ]
    return messages


def next_turn(llm: LLM, ctx: InterviewContext, transcript: list[Turn], plan: TurnPlan) -> LLMResult[InterviewerTurn]:
    return llm.structured(
        agent="interviewer",
        prompt=PROMPT,
        messages=build_messages(ctx, transcript, status_note(plan)),
        output_model=InterviewerTurn,
        effort=get_settings().interviewer_effort,
    )
