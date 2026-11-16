"""Persistent entities (SRS section 6)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)  # None for guests
    password_hash: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100), default="")
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_guest: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    sessions: Mapped[list["InterviewSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    cvs: Mapped[list["CV"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class CV(Base):
    """Only the extracted text is kept; the uploaded PDF is never written to disk (SRS 6.1)."""

    __tablename__ = "cvs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    extracted_text: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class InterviewSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    cv_id: Mapped[int | None] = mapped_column(ForeignKey("cvs.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(100))
    level: Mapped[str] = mapped_column(String(10))
    job_description: Mapped[str] = mapped_column(Text, default="")
    session_type: Mapped[str] = mapped_column(String(20), default="full")  # full / hr / technical
    personality: Mapped[str] = mapped_column(String(30), default="friendly_hr")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active / paused / completed
    question_limit: Mapped[int] = mapped_column(Integer, default=8)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")  # current target (FR-12)
    cv_text: Mapped[str] = mapped_column(Text, default="")  # snapshot, so deleting the CV keeps the record
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    user: Mapped[User | None] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Message.id"
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="Evaluation.message_id"
    )
    report: Mapped["Report | None"] = relationship(back_populates="session", cascade="all, delete-orphan")
    llm_calls: Mapped[list["LlmCall"]] = relationship(cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    speaker: Mapped[str] = mapped_column(String(12))  # interviewer / candidate / system
    # interviewer: question / follow_up / redirect / closing; candidate: answer / off_topic
    kind: Mapped[str] = mapped_column(String(12))
    round: Mapped[str] = mapped_column(String(10), default="technical")  # hr / technical / coding
    topic: Mapped[str | None] = mapped_column(String(100))
    difficulty: Mapped[str | None] = mapped_column(String(10))
    about_cv: Mapped[bool] = mapped_column(default=False)  # interviewer asked about a CV project (FR-13)
    quality: Mapped[str | None] = mapped_column(String(10))  # interviewer's quick read of a candidate answer
    text: Mapped[str] = mapped_column(Text)
    is_voice: Mapped[bool] = mapped_column(default=False)
    speech_seconds: Mapped[float | None] = mapped_column(Float)
    wpm: Mapped[float | None] = mapped_column(Float)
    filler_count: Mapped[int | None] = mapped_column(Integer)
    filler_words: Mapped[dict | None] = mapped_column(JSON)  # e.g. {"um": 3, "like": 2} (FR-43)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[InterviewSession] = relationship(back_populates="messages")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    topic: Mapped[str | None] = mapped_column(String(100))
    correctness: Mapped[int] = mapped_column(Integer)
    clarity: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer)
    star_flags: Mapped[dict | None] = mapped_column(JSON)
    feedback: Mapped[str] = mapped_column(Text)
    model_answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[InterviewSession] = relationship(back_populates="evaluations")

    @property
    def average(self) -> float:
        return round((self.correctness + self.clarity + self.depth) / 3, 1)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), unique=True)
    overall_score: Mapped[float] = mapped_column(Float)
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(Text, default="")
    study_plan: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[InterviewSession] = relationship(back_populates="report")


class LlmCall(Base):
    """One Claude call: tokens, latency and cost per agent step (NFR-18, FR-61)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(30))
    prompt: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
