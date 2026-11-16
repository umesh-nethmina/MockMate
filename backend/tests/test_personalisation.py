from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.models import Evaluation, InterviewSession, LlmCall
from tests.conftest import authed, register, turn

SETUP = {"role": "Python developer", "level": "junior"}


def interviewer_notes(fake_llm):
    return [c["messages"][-1]["content"][-1]["text"] for c in fake_llm.calls if c["agent"] == "interviewer"]


def test_full_interview_runs_hr_then_technical(client, fake_llm):
    sid = client.post("/sessions", json=SETUP).json()["session_id"]
    for _ in range(4):
        client.post(f"/sessions/{sid}/answer", json={"text": "answer"})
    rounds = [m["round"] for m in client.get(f"/sessions/{sid}").json()["messages"] if m["speaker"] == "interviewer"]
    assert rounds == ["hr", "hr", "hr", "technical", "technical"]
    notes = interviewer_notes(fake_llm)
    assert "Round for the next question: hr" in notes[0]
    assert "previous round is over" in notes[3]


def test_session_type_and_personality_reach_the_prompt(client, fake_llm):
    body = {**SETUP, "session_type": "technical", "personality": "fast_paced_founder"}
    res = client.post("/sessions", json=body).json()
    state = client.get(f"/sessions/{res['session_id']}").json()
    assert state["session_type"] == "technical" and state["personality"] == "fast_paced_founder"
    first = fake_llm.calls[0]["messages"][0]["content"][0]["text"]
    assert "Interview type: technical" in first and "startup founder" in first
    assert "Round for the next question: technical" in interviewer_notes(fake_llm)[0]


def test_coding_session_type_not_available_yet(client):
    assert client.post("/sessions", json={**SETUP, "session_type": "coding"}).status_code == 422


def test_difficulty_rises_after_strong_and_falls_after_two_weak(client, fake_llm, db):
    sid = client.post("/sessions", json={**SETUP, "session_type": "technical"}).json()["session_id"]
    fake_llm.queue.append(turn(previous_answer_quality="strong"))
    client.post(f"/sessions/{sid}/answer", json={"text": "great"})
    assert db.get(InterviewSession, sid).difficulty == "hard"

    for _ in range(2):
        fake_llm.queue.append(turn(previous_answer_quality="weak"))
        client.post(f"/sessions/{sid}/answer", json={"text": "meh"})
    db.expire_all()
    assert db.get(InterviewSession, sid).difficulty == "medium"
    client.post(f"/sessions/{sid}/answer", json={"text": "next"})
    assert "Target difficulty: medium" in interviewer_notes(fake_llm)[-1]
    assert "judged the answer before the latest one as: weak" in interviewer_notes(fake_llm)[-1]


def test_star_flags_only_for_hr_answers(client):
    sid = client.post("/sessions", json={**SETUP, "question_limit": 4}).json()["session_id"]  # 2 hr + 2 technical
    for _ in range(4):
        client.post(f"/sessions/{sid}/answer", json={"text": "answer"})
    report = client.post(f"/sessions/{sid}/end").json()
    stars = [(q["round"], q["star"]) for q in report["questions"]]
    assert stars[0] == ("hr", {"situation": True, "task": True, "action": True, "result": False})
    assert stars[-1] == ("technical", None)


# ---------- cost cap and usage (FR-61, FR-62) ----------

def test_daily_cost_cap_blocks_new_sessions_only(client, db, monkeypatch):
    sid = client.post("/sessions", json=SETUP).json()["session_id"]
    monkeypatch.setattr(get_settings(), "daily_cost_cap_usd", 0.5)
    db.add(LlmCall(agent="x", prompt="x", model="x", cost_usd=0.6))
    db.commit()

    res = client.post("/sessions", json=SETUP)
    assert res.status_code == 503 and "practice limit" in res.json()["error"]
    assert client.post(f"/sessions/{sid}/answer", json={"text": "still works"}).status_code == 200


def test_yesterdays_spend_does_not_count(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "daily_cost_cap_usd", 0.5)
    db.add(LlmCall(agent="x", prompt="x", model="x", cost_usd=5, created_at=datetime.now(UTC) - timedelta(days=1)))
    db.commit()
    assert client.post("/sessions", json=SETUP).status_code == 201


def test_admin_usage_report(anon, client, db, monkeypatch):
    sid = client.post("/sessions", json=SETUP).json()["session_id"]
    client.post(f"/sessions/{sid}/answer", json={"text": "a"})
    assert client.get("/admin/usage").status_code == 403

    monkeypatch.setattr(get_settings(), "admin_emails", ["admin@example.com"])
    admin = authed(register(anon, "admin@example.com"))
    data = admin.get("/admin/usage?days=3").json()
    assert len(data["days"]) == 3
    today = data["days"][-1]
    calls = db.query(LlmCall).count()
    assert today["calls"] == calls and today["sessions"] == 1
    assert data["spent_today_usd"] == round(calls * 0.001, 4)
    assert data["recent_sessions"][0]["id"] == sid
    assert data["recent_sessions"][0]["user_email"] == "user@example.com"
    assert db.query(Evaluation).count() == 1
