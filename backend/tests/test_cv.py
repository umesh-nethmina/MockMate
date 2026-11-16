import pytest

from app.config import get_settings
from app.tools.cv_parser import CVParseError, extract_text
from tests.conftest import authed, make_pdf, register, turn

CV_TEXT = "Jane Doe. Projects: Chess engine in Python with alpha-beta search. Internship at Acme."


def upload(c, data: bytes, name="cv.pdf", ctype="application/pdf"):
    return c.post("/cv", files={"file": (name, data, ctype)})


def test_extract_text_from_pdf():
    parsed = extract_text(make_pdf(CV_TEXT), max_chars=10_000)
    assert "Chess engine" in parsed.text and parsed.pages == 1 and parsed.truncated is False


def test_extract_text_truncates_and_reports_it():
    parsed = extract_text(make_pdf(CV_TEXT), max_chars=60)
    assert len(parsed.text) == 60 and parsed.truncated is True


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"hello", "not a PDF"),
        (b"%PDF-1.4 garbage", "could not read"),
        (make_pdf(""), "scanned image"),
    ],
)
def test_extract_text_errors(data, message):
    with pytest.raises(CVParseError, match=message):
        extract_text(data, max_chars=1000)


def test_upload_list_and_delete(client):
    res = upload(client, make_pdf(CV_TEXT))
    assert res.status_code == 201, res.text
    cv = res.json()
    assert cv["file_name"] == "cv.pdf" and "Chess engine" in cv["preview"]
    assert [c["id"] for c in client.get("/cv").json()] == [cv["id"]]
    assert client.delete(f"/cv/{cv['id']}").status_code == 204
    assert client.get("/cv").json() == []


def test_upload_rejects_wrong_type_size_and_unreadable(client, monkeypatch):
    assert upload(client, b"text", name="cv.txt", ctype="text/plain").status_code == 415
    assert upload(client, b"text", name="cv.pdf").status_code == 422
    monkeypatch.setattr(get_settings(), "cv_max_bytes", 100)
    res = upload(client, make_pdf(CV_TEXT))
    assert res.status_code == 413 and "5 MB" in res.json()["error"]


def test_upload_requires_login(anon):
    assert upload(anon, make_pdf(CV_TEXT)).status_code == 401


def test_cvs_are_private(client, anon):
    cv_id = upload(client, make_pdf(CV_TEXT)).json()["id"]
    other = authed(register(anon, "other@example.com"))
    assert other.get("/cv").json() == []
    assert other.delete(f"/cv/{cv_id}").status_code == 404
    res = other.post("/sessions", json={"role": "Dev", "level": "junior", "cv_id": cv_id})
    assert res.status_code == 404


def test_cv_reaches_interviewer_and_cv_question_is_forced(client, fake_llm):
    cv_id = upload(client, make_pdf(CV_TEXT)).json()["id"]
    sid = client.post("/sessions", json={"role": "Dev", "level": "junior", "cv_id": cv_id}).json()["session_id"]
    first_call = fake_llm.calls[0]["messages"][0]["content"]
    first_text = first_call if isinstance(first_call, str) else first_call[0]["text"]
    assert "<cv>" in first_text and "Chess engine" in first_text

    client.post(f"/sessions/{sid}/answer", json={"text": "a"})  # plans question 2: CV question "soon"
    client.post(f"/sessions/{sid}/answer", json={"text": "b"})  # plans question 3: CV question "now"
    notes = [c["messages"][-1]["content"][-1]["text"] for c in fake_llm.calls if c["agent"] == "interviewer"]
    assert "within the next two" in notes[1]
    assert "must be about a specific project" in notes[2]

    fake_llm.queue.append(turn(about_cv_project=True, question="Tell me about your chess engine."))
    client.post(f"/sessions/{sid}/answer", json={"text": "c"})
    client.post(f"/sessions/{sid}/answer", json={"text": "d"})
    notes = [c["messages"][-1]["content"][-1]["text"] for c in fake_llm.calls if c["agent"] == "interviewer"]
    assert "CV" not in notes[-1]  # done once asked (FR-13)


def test_session_keeps_cv_text_after_cv_is_deleted(client):
    cv_id = upload(client, make_pdf(CV_TEXT)).json()["id"]
    sid = client.post("/sessions", json={"role": "Dev", "level": "junior", "cv_id": cv_id}).json()["session_id"]
    client.delete(f"/cv/{cv_id}")
    assert client.get(f"/sessions/{sid}").json()["has_cv"] is True
