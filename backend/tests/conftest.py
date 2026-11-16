from collections import deque

import pytest
from fastapi.testclient import TestClient

from app import db as database
from app.agents.evaluator import AnswerScore, ReportSummary
from app.agents.interviewer import InterviewerTurn
from app.db import Base, configure_database
from app.llm import LLMError, LLMResult, LLMUsage, get_llm
from app.main import app


class FakeLLM:
    """Stands in for Claude (NFR-16). Queue outputs or errors; otherwise returns sensible defaults."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.queue: deque = deque()  # items: BaseModel output or Exception, consumed in order
        self.n = 0

    def structured(self, *, agent, prompt, messages, output_model, effort, max_tokens=8000):
        self.calls.append({"agent": agent, "prompt": prompt, "messages": messages, "effort": effort})
        usage = LLMUsage(agent=agent, prompt=prompt, model="fake", input_tokens=100, output_tokens=50,
                         latency_ms=5, cost_usd=0.001)
        if self.queue and isinstance(self.queue[0], Exception | output_model):
            item = self.queue.popleft()
            if isinstance(item, Exception):
                raise item
            return LLMResult(item, usage)
        if output_model is InterviewerTurn:
            self.n += 1
            out = InterviewerTurn(decision="next_topic", round="technical", topic=f"Topic {self.n}",
                                  difficulty="medium", question=f"Question {self.n}?")
        elif output_model is AnswerScore:
            out = AnswerScore(correctness=8, clarity=6, depth=7, feedback="Good.", model_answer="Model.")
        elif output_model is ReportSummary:
            out = ReportSummary(strengths=["s"], weaknesses=["w"], summary="Summary.")
        else:  # pragma: no cover
            raise AssertionError(output_model)
        return LLMResult(out, usage)

    def agents(self) -> list[str]:
        return [c["agent"] for c in self.calls]


@pytest.fixture
def engine():
    eng = configure_database("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    with database.SessionLocal() as session:
        yield session


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(engine, fake_llm):
    app.dependency_overrides[get_llm] = lambda: fake_llm
    yield TestClient(app)  # not used as a context manager, so start-up migrations do not run
    app.dependency_overrides.clear()


@pytest.fixture
def llm_error():
    return LLMError("boom")
