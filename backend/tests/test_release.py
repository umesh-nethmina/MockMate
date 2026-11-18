"""Phase 6: PDF report download (FR-45) and personal data export (NFR-10)."""

import io

from pypdf import PdfReader

from app.models import CodingProblem
from tests.conftest import authed, register
from tests.test_coding import PROBLEM

SETUP = {"role": "Data analyst / BI", "level": "junior", "question_limit": 2}


def finished(client, **extra) -> str:
    sid = client.post("/sessions", json={**SETUP, **extra}).json()["session_id"]
    answer = "I’d use a window function — it’s cleaner. Ünïcode ✓"
    client.post(f"/sessions/{sid}/answer", json={"text": answer})
    client.post(f"/sessions/{sid}/answer", json={"text": "Second answer.", "is_voice": True, "speech_seconds": 4})
    client.post(f"/sessions/{sid}/end")
    return sid


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_report_pdf_downloads_with_unicode_and_all_sections(client):
    sid = finished(client, panel=True)
    client.post(f"/sessions/{sid}/study-plan")
    res = client.get(f"/sessions/{sid}/report.pdf")
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].startswith('attachment; filename="mockmate-data-analyst-bi-')
    assert res.content.startswith(b"%PDF")
    text = pdf_text(res.content)
    for expected in ["Data analyst / BI (junior) interview report", "Strengths", "To improve", "Panel decision",
                     "How you spoke", "Q1", "Your answer", "window function", "Ünïcode", "Model answer",
                     "Your study plan", "not a hiring decision"]:
        assert expected in text, expected


def test_report_pdf_for_coding_session(client, db, fake_sandbox):
    db.add(CodingProblem(**PROBLEM))
    db.commit()
    sid = client.post("/sessions", json={"role": "Backend developer", "level": "junior",
                                         "session_type": "coding"}).json()["session_id"]
    code = "def add_two(a, b):\n    return a + b\n"
    client.post(f"/sessions/{sid}/code/submit", json={"language": "python", "code": code})
    client.post(f"/sessions/{sid}/end")
    text = pdf_text(client.get(f"/sessions/{sid}/report.pdf").content)
    assert "Your code (Python)" in text and "4 of 4 tests passed" in text and "return a + b" in text


def test_report_pdf_needs_report_and_ownership(client, anon):
    sid = client.post("/sessions", json=SETUP).json()["session_id"]
    assert client.get(f"/sessions/{sid}/report.pdf").status_code == 404
    client.post(f"/sessions/{sid}/end")
    assert client.get(f"/sessions/{sid}/report.pdf").status_code == 200  # empty report still renders
    other = authed(register(anon, "other@example.com"))
    assert other.get(f"/sessions/{sid}/report.pdf").status_code == 404


def test_export_contains_all_user_data_but_no_secrets(client, anon):
    from tests.conftest import make_pdf

    cv = make_pdf("Built a Flask API for a student society " * 3)
    client.post("/cv", files={"file": ("cv.pdf", cv, "application/pdf")})
    sid = finished(client)
    other = authed(register(anon, "other@example.com"))
    finished(other)

    res = client.get("/users/me/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith('attachment; filename="mockmate-data-')
    data = res.json()
    assert data["format"] == "mockmate-export-v1"
    assert data["account"]["email"] == "user@example.com" and "password_hash" not in data["account"]
    assert len(data["cvs"]) == 1 and "Flask" in data["cvs"][0]["extracted_text"]
    assert [s["id"] for s in data["sessions"]] == [sid]  # only this user's sessions
    s = data["sessions"][0]
    assert len(s["messages"]) >= 4 and len(s["evaluations"]) == 2 and s["report"]["overall_score"] > 0
    assert any(m["is_voice"] for m in s["messages"])
    assert "s3cret" not in res.text


def test_export_requires_login(anon):
    assert anon.get("/users/me/export").status_code in (401, 403)
