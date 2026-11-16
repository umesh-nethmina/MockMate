"""Phase 5: progress dashboard (FR-51), weak-topic focus (FR-52), study plan (FR-53), panel mode (FR-44)."""

from datetime import UTC, datetime, timedelta

from app import progress
from app.agents.evaluator import PanelistVerdict, PanelVerdicts
from app.agents.interviewer import TurnPlan, status_note
from app.models import Evaluation, InterviewSession, Message, Report
from tests.conftest import authed, register, turn

SETUP = {"role": "Python developer", "level": "junior"}


def user_id(client) -> int:
    return client.get("/users/me").json()["id"]


def past_session(db, uid: int, scores: dict[str, tuple[str, int]], days_ago: int = 1) -> InterviewSession:
    """A finished session where each topic got the given (round, score on all three dimensions)."""
    s = InterviewSession(
        user_id=uid, role="Python developer", level="junior", status="completed",
        started_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(s)
    db.flush()
    for topic, (rnd, score) in scores.items():
        q = Message(session_id=s.id, speaker="interviewer", kind="question", round=rnd, topic=topic, text="Q?")
        a = Message(session_id=s.id, speaker="candidate", kind="answer", round=rnd, topic=topic, text="A.")
        db.add_all([q, a])
        db.flush()
        db.add(Evaluation(session_id=s.id, message_id=a.id, topic=topic, correctness=score, clarity=score,
                          depth=score, feedback="f", model_answer="m"))
    avg = sum(sc for _, sc in scores.values()) / len(scores)
    db.add(Report(session_id=s.id, overall_score=round(avg, 1), strengths=[], weaknesses=[]))
    db.commit()
    return s


def notes(fake_llm) -> list[str]:
    return [c["messages"][-1]["content"][-1]["text"] for c in fake_llm.calls if c["agent"] == "interviewer"]


# ---------- FR-51 ----------

def test_progress_empty(client):
    p = client.get("/users/me/progress").json()
    assert p["sessions_completed"] == 0 and p["trend"] == [] and p["weakest_topics"] == []
    assert p["dimensions"] == {"correctness": None, "clarity": None, "depth": None}


def test_progress_trend_weakest_topics_and_dimensions(client, db):
    uid = user_id(client)
    past_session(db, uid, {"Python generators": ("technical", 3), "Teamwork": ("hr", 8)}, days_ago=3)
    past_session(db, uid, {"python   Generators": ("technical", 5), "SQL joins": ("technical", 6)}, days_ago=1)
    p = client.get("/users/me/progress").json()
    assert p["sessions_completed"] == 2 and [t["score"] for t in p["trend"]] == [5.5, 5.5]
    weakest = p["weakest_topics"]
    assert [t["topic"] for t in weakest] == ["python   Generators", "SQL joins"]  # merged; latest wording
    assert weakest[0]["answers"] == 2 and weakest[0]["average"] == 4.0
    assert [t["topic"] for t in p["strongest_topics"]] == ["Teamwork"]
    assert p["dimensions"]["correctness"] == 5.5 and p["answers_scored"] == 4


def test_progress_is_per_user(client, anon, db):
    past_session(db, user_id(client), {"Python generators": ("technical", 3)})
    other = authed(register(anon, "other@example.com"))
    assert other.get("/users/me/progress").json()["sessions_completed"] == 0


def test_topic_matching():
    assert progress.same_topic("Python generators", "python  GENERATORS")
    assert progress.same_topic("generators", "Python generators")
    assert not progress.same_topic("SQL joins", "Python generators")
    assert not progress.same_topic("", "x")


# ---------- FR-52: exit criterion ----------

def test_second_session_favours_weak_topics(client, db, fake_llm):
    past_session(db, user_id(client), {"Python generators": ("technical", 3), "REST APIs": ("technical", 5),
                                       "Teamwork": ("hr", 9)})
    sid = client.post("/sessions", json={**SETUP, "session_type": "technical"}).json()["session_id"]
    state = client.get(f"/sessions/{sid}").json()
    assert state["focus_topics"] == ["Python generators", "REST APIs"]  # weakest first, strong topics ignored

    first_note = notes(fake_llm)[0]
    assert 'Weak topic from the candidate\'s earlier sessions: "Python generators"' in first_note
    assert 'set `topic` to exactly "Python generators"' in first_note

    # The fake asked about "Topic 1"; generators is still due. Now the interviewer covers it...
    fake_llm.queue.append(turn(topic="Python generators"))
    client.post(f"/sessions/{sid}/answer", json={"text": "answer 1"})
    assert '"Python generators"' in notes(fake_llm)[1]
    client.post(f"/sessions/{sid}/answer", json={"text": "answer 2"})
    # ...so the next weak topic takes its place, and once both are covered the note stops asking
    assert '"REST APIs"' in notes(fake_llm)[2] and "Python generators" not in notes(fake_llm)[2]
    fake_llm.queue.append(turn(topic="REST API design"))
    client.post(f"/sessions/{sid}/answer", json={"text": "answer 3"})
    client.post(f"/sessions/{sid}/answer", json={"text": "answer 4"})
    assert "Weak topic" not in notes(fake_llm)[4]


def test_focus_can_be_turned_off_and_respects_rounds(client, db, fake_llm):
    past_session(db, user_id(client), {"Python generators": ("technical", 3), "Conflict handling": ("hr", 4)})
    off = client.post("/sessions", json={**SETUP, "session_type": "technical", "focus_weak_topics": False}).json()
    assert client.get(f"/sessions/{off['session_id']}").json()["focus_topics"] == []
    hr = client.post("/sessions", json={**SETUP, "session_type": "hr"}).json()
    assert client.get(f"/sessions/{hr['session_id']}").json()["focus_topics"] == ["Conflict handling"]
    coding = progress.focus_topics_for(db, user_id(client), "coding")
    assert coding == []


def test_cv_question_takes_priority_over_focus():
    plan = TurnPlan(questions_asked=2, question_limit=8, round="technical", difficulty="medium",
                    cv_due="now", focus_topic="Python generators")
    note = status_note(plan)
    assert "CV" in note and "Weak topic" not in note
    assert "Weak topic" in status_note(TurnPlan(2, 8, "technical", "medium", cv_due="soon",
                                                focus_topic="Python generators"))


# ---------- FR-44 ----------

def test_panel_mode_rotates_interviewers_and_votes(client, fake_llm):
    res = client.post("/sessions", json={**SETUP, "session_type": "full", "panel": True, "question_limit": 4}).json()
    sid = res["session_id"]
    assert res["message"]["persona"] == "friendly_hr"  # full interview opens with HR
    first = fake_llm.calls[0]["messages"][0]["content"][0]["text"]
    assert first.count("<panelist") == 3 and "(panel interview)" in first
    assert "Panel: this message is spoken by Priya, HR partner" in notes(fake_llm)[0]

    fake_llm.queue.append(turn(decision="follow_up", round="hr"))
    reply = client.post(f"/sessions/{sid}/answer", json={"text": "a1"}).json()
    assert reply["message"]["persona"] == "friendly_hr"  # follow-up stays with the same panelist
    reply = client.post(f"/sessions/{sid}/answer", json={"text": "a2"}).json()
    assert reply["message"]["persona"] == "strict_tech_lead"  # first technical topic
    assert "a new topic is spoken by Marcus, tech lead" in notes(fake_llm)[2]
    reply = client.post(f"/sessions/{sid}/answer", json={"text": "a3"}).json()
    assert reply["message"]["persona"] == "fast_paced_founder"  # technical topics alternate
    client.post(f"/sessions/{sid}/answer", json={"text": "a4"})

    report = client.post(f"/sessions/{sid}/end").json()
    verdict = report["panel_verdict"]
    assert verdict["decision"] == "hire" and verdict["votes_for_hire"] == 2
    assert [p["name"] for p in verdict["panelists"]] == ["Priya, HR partner", "Marcus, tech lead", "Sam, founder"]
    assert "panel" in [c["prompt"] for c in fake_llm.calls if c["agent"] == "report"][-1]


def test_panel_majority_is_computed_not_trusted(client, fake_llm):
    sid = client.post("/sessions", json={**SETUP, "panel": True, "question_limit": 1}).json()["session_id"]
    client.post(f"/sessions/{sid}/answer", json={"text": "a"})
    fake_llm.queue.append(PanelVerdicts(
        verdicts=[
            PanelistVerdict(panelist="friendly_hr", decision="strong_hire", reason="r"),
            PanelistVerdict(panelist="friendly_hr", decision="hire", reason="duplicate vote ignored"),
            PanelistVerdict(panelist="strict_tech_lead", decision="no_hire", reason="r"),
            PanelistVerdict(panelist="fast_paced_founder", decision="strong_no_hire", reason="r"),
        ],
        summary="s",
    ))
    verdict = client.post(f"/sessions/{sid}/end").json()["panel_verdict"]
    assert verdict["decision"] == "no_hire" and verdict["votes_for_hire"] == 1 and len(verdict["panelists"]) == 3


def test_non_panel_sessions_have_no_personas_or_verdict(client):
    res = client.post("/sessions", json={**SETUP, "question_limit": 1}).json()
    assert res["message"]["persona"] is None
    client.post(f"/sessions/{res['session_id']}/answer", json={"text": "a"})
    assert client.post(f"/sessions/{res['session_id']}/end").json()["panel_verdict"] is None


# ---------- FR-53 ----------

def test_study_plan_is_created_once_from_report_and_history(client, anon, db, fake_llm):
    past_session(db, user_id(client), {"Python generators": ("technical", 3)}, days_ago=5)
    sid = client.post("/sessions", json={**SETUP, "question_limit": 1}).json()["session_id"]
    assert client.post(f"/sessions/{sid}/study-plan").status_code == 409  # no report yet
    client.post(f"/sessions/{sid}/answer", json={"text": "a"})
    assert client.post(f"/sessions/{sid}/end").json()["study_plan"] is None  # not made automatically

    report = client.post(f"/sessions/{sid}/study-plan").json()
    plan = report["study_plan"]
    assert plan["items"] and plan["next_session"]
    call = [c for c in fake_llm.calls if c["agent"] == "study_plan"]
    assert len(call) == 1 and call[0]["prompt"] == "study_plan.v1"
    content = call[0]["messages"][0]["content"]
    assert "<weak_topics_history>" in content and "Python generators" in content and "<this_session>" in content

    again = client.post(f"/sessions/{sid}/study-plan").json()
    assert again["study_plan"] == plan and len([c for c in fake_llm.calls if c["agent"] == "study_plan"]) == 1
    assert client.get(f"/sessions/{sid}/report").json()["study_plan"] == plan

    other = authed(register(anon, "other@example.com"))
    assert other.post(f"/sessions/{sid}/study-plan").status_code == 404


def test_study_plan_needs_scored_answers(client):
    sid = client.post("/sessions", json=SETUP).json()["session_id"]
    client.post(f"/sessions/{sid}/end")
    res = client.post(f"/sessions/{sid}/study-plan")
    assert res.status_code == 409 and "no scored answers" in res.json()["error"]


def test_study_plan_llm_failure_is_friendly(client, fake_llm):
    from app.llm import LLMError

    sid = client.post("/sessions", json={**SETUP, "question_limit": 1}).json()["session_id"]
    client.post(f"/sessions/{sid}/answer", json={"text": "a"})
    client.post(f"/sessions/{sid}/end")
    fake_llm.queue.append(LLMError("boom"))
    assert client.post(f"/sessions/{sid}/study-plan").status_code == 503
    assert client.get(f"/sessions/{sid}/report").json()["study_plan"] is None
