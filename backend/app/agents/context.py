from dataclasses import dataclass
from html import escape

from app.llm.prompts import load_prompt

PERSONALITIES = ("friendly_hr", "strict_tech_lead", "fast_paced_founder")


@dataclass(frozen=True)
class InterviewContext:
    """Plain, thread-safe snapshot of the session setup that every agent needs."""

    role: str
    level: str
    job_description: str
    cv_text: str = ""
    personality: str = "friendly_hr"
    session_type: str = "full"

    def as_prompt(self, include_style: bool = True, include_cv: bool = True) -> str:
        parts = [
            f"Target role: {escape(self.role, quote=False)}",
            f"Level: {self.level}",
            f"Interview type: {self.session_type}",
        ]
        if include_style:
            style = load_prompt(f"personality.{self.personality}.v1")
            parts.append(f"<interviewer_style>\n{style}\n</interviewer_style>")
        parts.append(tag("job_description", self.job_description.strip() or "(none provided)"))
        if include_cv and self.cv_text.strip():
            parts.append(tag("cv", self.cv_text.strip()))
        return "\n".join(parts)


def tag(name: str, text: str) -> str:
    """Wrap untrusted text in a tag; escaping stops it from closing the tag early (NFR-09)."""
    return f"<{name}>\n{escape(text, quote=False)}\n</{name}>"
