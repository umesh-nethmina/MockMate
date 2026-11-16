import pytest
from fastapi.testclient import TestClient

from app import db as database
from app.agents.interviewer import InterviewerTurn
from app.db import Base, configure_database
from app.llm import get_llm
from app.llm.fake import FakeLLM
from app.main import app
from app.tools.sandbox import RunResult, SandboxUnavailable, TestOutcome, get_sandbox

PASSWORD = "s3cret-pass"


@pytest.fixture
def engine():
    eng = configure_database("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine):
    with database.SessionLocal() as session:
        yield session


@pytest.fixture
def fake_llm():
    return FakeLLM()


class FakeSandbox:
    """Stands in for Docker in API tests. Code containing '# wrong' fails every test; otherwise all pass.
    Queue a RunResult in `next` to return it once."""

    def __init__(self) -> None:
        self.up = True
        self.calls: list[dict] = []
        self.next: RunResult | None = None

    def available(self) -> bool:
        return self.up

    def run(self, language, code, function, tests):
        self.calls.append({"language": language, "code": code, "function": function, "tests": tests})
        if not self.up:
            raise SandboxUnavailable()
        if self.next is not None:
            result, self.next = self.next, None
            return result
        ok = "# wrong" not in code
        return RunResult(
            "ok", [TestOutcome(ok=ok, output=t["expected"] if ok else None, ms=1.0) for t in tests], duration_ms=5
        )


@pytest.fixture
def fake_sandbox():
    return FakeSandbox()


@pytest.fixture
def anon(engine, fake_llm, fake_sandbox):
    """Client without a token. Not used as a context manager, so start-up migrations do not run."""
    app.dependency_overrides[get_llm] = lambda: fake_llm
    app.dependency_overrides[get_sandbox] = lambda: fake_sandbox
    yield TestClient(app)
    app.dependency_overrides.clear()


def register(c: TestClient, email: str = "user@example.com", password: str = PASSWORD) -> str:
    res = c.post("/auth/register", json={"email": email, "password": password, "name": "Test"})
    assert res.status_code == 201, res.text
    return res.json()["access_token"]


def authed(token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def client(anon):
    """Client logged in as a registered user."""
    return authed(register(anon))


@pytest.fixture
def guest(anon):
    return authed(anon.post("/auth/guest").json()["access_token"])


def turn(**overrides) -> InterviewerTurn:
    data = {
        "decision": "next_topic",
        "previous_answer_quality": "adequate",
        "round": "technical",
        "topic": "Topic",
        "difficulty": "medium",
        "about_cv_project": False,
        "question": "Next question?",
    }
    return InterviewerTurn(**{**data, **overrides})


def make_pdf(text: str) -> bytes:
    """Smallest valid one-page PDF with a line of text, for CV upload tests."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out
