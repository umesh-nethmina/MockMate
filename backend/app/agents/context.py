from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class InterviewContext:
    """Plain, thread-safe snapshot of the session setup that every agent needs."""

    role: str
    level: str
    job_description: str

    def as_prompt(self) -> str:
        jd = escape(self.job_description.strip(), quote=False) or "(none provided)"
        return (
            f"Target role: {escape(self.role, quote=False)}\n"
            f"Level: {self.level}\n"
            f"<job_description>\n{jd}\n</job_description>"
        )


def tag(name: str, text: str) -> str:
    """Wrap untrusted text in a tag; escaping stops it from closing the tag early (NFR-09)."""
    return f"<{name}>\n{escape(text, quote=False)}\n</{name}>"
