"""Interviewer agent: picks follow-up vs next topic and writes the next question (FR-10, FR-11, FR-16)."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.context import InterviewContext
from app.config import get_settings
from app.llm import LLM, LLMResult

PROMPT = "interviewer.v1"
MAX_FOLLOW_UPS_PER_TOPIC = 2


class InterviewerTurn(BaseModel):
    decision: Literal["follow_up", "next_topic", "redirect"]
    round: Literal["hr", "technical"]
    topic: str = Field(description="2-4 word label for the skill or subject being tested")
    difficulty: Literal["easy", "medium", "hard"]
    question: str = Field(description="Exact words said to the candidate")


@dataclass(frozen=True)
class Turn:
    """One line of transcript as the interviewer sees it."""

    speaker: Literal["interviewer", "candidate"]
    text: str


def status_note(questions_asked: int, question_limit: int, follow_ups_on_topic: int) -> str:
    if questions_asked == 0:
        return f"Start of the interview. Questions planned: {question_limit}."
    parts = [f"Questions asked so far: {questions_asked} of {question_limit}."]
    if follow_ups_on_topic >= MAX_FOLLOW_UPS_PER_TOPIC:
        parts.append("No more follow-ups are allowed on the current topic: use next_topic or redirect.")
    else:
        parts.append(
            f"Follow-ups already asked on the current topic: {follow_ups_on_topic} "
            f"(max {MAX_FOLLOW_UPS_PER_TOPIC})."
        )
    if questions_asked == question_limit - 1:
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


def next_turn(
    llm: LLM,
    ctx: InterviewContext,
    transcript: list[Turn],
    *,
    questions_asked: int,
    question_limit: int,
    follow_ups_on_topic: int,
) -> LLMResult[InterviewerTurn]:
    note = status_note(questions_asked, question_limit, follow_ups_on_topic)
    return llm.structured(
        agent="interviewer",
        prompt=PROMPT,
        messages=build_messages(ctx, transcript, note),
        output_model=InterviewerTurn,
        effort=get_settings().interviewer_effort,
    )
