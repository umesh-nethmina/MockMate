"""Coding round API (FR-30..FR-34) and admin problem management (FR-60, UC-05), with a fake sandbox."""

import json

import pytest

from app import coding
from app.config import get_settings
from app.models import CodeRun, CodingProblem, Evaluation, InterviewSession
from app.tools.sandbox import RunResult, TestOutcome
from tests.conftest import authed, register

SETUP = {"role": "Backend developer", "level": "junior", "session_type": "coding"}

PROBLEM = {
    "title": "Add Two Numbers",
    "difficulty": "easy",
    "topic": "Warm-up",
    "statement": "Return the sum of a and b.",
    "function_name": "add_two",
    "params": ["a", "b"],
    "tests": [
        {"args": [1, 2], "expected": 3, "hidden": False},
        {"args": [2, 2], "expected": 4, "hidden": False},
        {"args": [-1, 1], "expected": 0, "hidden": True},
        {"args": [10, 5], "expected": 15, "hidden": True},
    ],
    "hints": ["Use the + operator.", "return a + b"],
    "reference_solution": "def add_two(a, b):\n    return a + b\n",
    "expected_complexity": "O(1) time and space",
}


@pytest.fixture
def problem(db):
    p = CodingProblem(**PROBLEM)
    db.add(p)
    db.commit()
    return p


def start(client) -> str:
    res = client.post("/sessions", json=SETUP)
    assert res.status_code == 201, res.text
    return res.json()["session_id"]


def test_start_coding_session_picks_problem_without_calling_claude(client, problem, fake_llm):
    res = client.post("/sessions", json=SETUP).json()
    assert res["message"]["round"] == "coding" and "Add Two Numbers" in res["message"]["text"]
    assert res["question_limit"] == 2 and res["questions_asked"] == 1
    assert fake_llm.calls == []

    p = client.get(f"/sessions/{res['session_id']}/problem").json()
    assert p["title"] == "Add Two Numbers" and p["hidden_tests"] == 2 and p["hints_total"] == 2
    assert p["samples"] == [{"args": [1, 2], "expected": 3}, {"args": [2, 2], "expected": 4}]
    assert p["function_names"] == {"python": "add_two", "javascript": "addTwo"}
    assert p["starter_code"]["python"].startswith("def add_two(a, b):")
    assert p["starter_code"]["javascript"].startswith("function addTwo(a, b) {")
    assert p["last_run"] is None and p["submitted"] is False
    assert "-1" not in json.dumps(p["samples"])  # hidden inputs never reach the client (FR-32)


def test_coding_needs_sandbox_problems_and_an_account(client, guest, fake_sandbox, db):
    assert client.post("/sessions", json=SETUP).status_code == 503  # no problems yet
    db.add(CodingProblem(**PROBLEM))
    db.commit()
    fake_sandbox.up = False
    res = client.post("/sessions", json=SETUP)
    assert res.status_code == 503 and "not available" in res.json()["error"]
    assert guest.post("/sessions", json=SETUP).status_code == 403


def test_run_uses_sample_tests_only_and_is_saved(client, problem, fake_sandbox):
    sid = start(client)
    res = client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "def add_two(a, b): return a+b"})
    assert res.status_code == 200, res.text
    run = res.json()
    assert run["status"] == "ok" and run["passed"] == 2 and run["total"] == 2 and run["hidden_total"] == 0
    assert [r["args"] for r in run["results"]] == [[1, 2], [2, 2]]
    assert fake_sandbox.calls[0]["function"] == "add_two"
    assert len(fake_sandbox.calls[0]["tests"]) == 2 and "hidden" not in fake_sandbox.calls[0]["tests"][0]

    client.post(f"/sessions/{sid}/code/run", json={"language": "javascript", "code": "function addTwo(a,b){}"})
    assert fake_sandbox.calls[1]["function"] == "addTwo"
    last = client.get(f"/sessions/{sid}/problem").json()["last_run"]
    assert last["language"] == "javascript" and last["code"] == "function addTwo(a,b){}"  # restored on refresh


def test_compile_errors_and_limits_are_reported(client, problem, fake_sandbox):
    sid = start(client)
    fake_sandbox.next = RunResult("compile_error", message="SyntaxError: invalid syntax (line 1)")
    run = client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "def ("}).json()
    assert run["status"] == "compile_error" and run["passed"] == 0 and "line 1" in run["message"]
    assert all(r["ok"] is False for r in run["results"])

    fake_sandbox.up = False
    res = client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "x"})
    assert res.status_code == 503 and "code runner" in res.json()["error"]


def test_run_limit_per_session(client, problem, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_code_runs_per_session", 1)
    sid = start(client)
    assert client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "x"}).status_code == 200
    assert client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "x"}).status_code == 429


def test_hints_are_graduated_and_limited(client, problem):
    sid = start(client)
    first = client.post(f"/sessions/{sid}/code/hint").json()
    assert first["hints_used"] == 1 and first["message"]["kind"] == "hint"
    assert first["message"]["text"] == "Hint 1 of 2: Use the + operator."
    assert client.post(f"/sessions/{sid}/code/hint").json()["hints_used"] == 2
    res = client.post(f"/sessions/{sid}/code/hint")
    assert res.status_code == 409 and "no more hints" in res.json()["error"]


def test_answer_before_submitting_code_is_rejected(client, problem):
    sid = start(client)
    res = client.post(f"/sessions/{sid}/answer", json={"text": "my approach is..."})
    assert res.status_code == 409 and "Submit your code first" in res.json()["error"]


def test_full_coding_flow_with_hidden_tests_follow_up_and_report(client, problem, fake_sandbox, fake_llm, db):
    sid = start(client)
    client.post(f"/sessions/{sid}/code/hint")
    fake_sandbox.next = RunResult(
        "ok",
        [TestOutcome(ok=True, output=3), TestOutcome(ok=True, output=4),
         TestOutcome(ok=True, output=0), TestOutcome(ok=False, error="IndexError: list index out of range (line 4)")],
    )
    code = "def add_two(a, b):\n    return a + b\n"
    res = client.post(f"/sessions/{sid}/code/submit", json={"language": "python", "code": code})
    assert res.status_code == 200, res.text
    body = res.json()
    run = body["run"]
    assert (run["passed"], run["total"], run["hidden_passed"], run["hidden_total"]) == (2, 2, 1, 2)
    hidden = [r for r in run["results"] if r["hidden"]]
    assert hidden[1] == {"hidden": True, "ok": False, "error": "IndexError"}  # no input, no details
    assert "args" not in hidden[0] and "expected" not in hidden[0]
    assert body["message"]["kind"] == "follow_up" and "complexity" in body["message"]["text"]  # FR-34
    assert len(fake_sandbox.calls[0]["tests"]) == 4

    # The code was scored in the background: correctness from tests (3/4 -> 8) minus 1 for the hint
    assert fake_llm.agents() == ["evaluator"] and fake_llm.calls[0]["prompt"] == "code_review.v1"
    assert "<candidate_code>" in fake_llm.calls[0]["messages"][0]["content"]
    assert "3 of 4 tests passed" in fake_llm.calls[0]["messages"][0]["content"]
    ev = db.query(Evaluation).one()
    assert (ev.correctness, ev.clarity, ev.depth) == (7, 7, 6)

    # No more runs, hints or submissions after submitting
    assert client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "x"}).status_code == 409
    assert client.post(f"/sessions/{sid}/code/hint").status_code == 409
    assert client.post(f"/sessions/{sid}/code/submit", json={"language": "python", "code": code}).status_code == 409

    # Complexity answer closes the interview; its evaluation sees the submitted code
    turn = client.post(f"/sessions/{sid}/answer", json={"text": "O(1) time and O(1) space."}).json()
    assert turn["done"] is True and turn["message"]["kind"] == "closing"
    follow_up_call = fake_llm.calls[1]
    assert follow_up_call["prompt"] == "evaluator.v3"
    content = follow_up_call["messages"][0]["content"]
    assert "<candidate_code>" in content and "Round: coding" in content and "O(1) time and space" in content

    report = client.post(f"/sessions/{sid}/end").json()
    kinds = [q["kind"] for q in report["questions"]]
    assert kinds == ["code", "answer"]
    code_q = report["questions"][0]
    assert code_q["question"].startswith("Add Two Numbers:") and code_q["answer"] == code
    assert (code_q["language"], code_q["tests_passed"], code_q["tests_total"], code_q["hints_used"]) == (
        "python", 3, 4, 1
    )
    assert code_q["star"] is None and report["delivery"]["voice_answers"] == 0
    assert report["questions"][1]["question"].startswith("Thanks for submitting")


def test_end_scores_code_if_background_evaluation_failed(client, problem, fake_llm, db):
    from app.llm import LLMError

    sid = start(client)
    fake_llm.queue.append(LLMError("boom"))  # background code review fails
    client.post(f"/sessions/{sid}/code/submit", json={"language": "python", "code": "def add_two(a, b): # wrong"})
    assert db.query(Evaluation).count() == 0
    report = client.post(f"/sessions/{sid}/end").json()  # ended early, before the follow-up answer
    assert [q["kind"] for q in report["questions"]] == ["code"]
    assert report["questions"][0]["correctness"] == 1 and report["questions"][0]["tests_passed"] == 0


def test_end_without_submission_gives_empty_report(client, problem):
    sid = start(client)
    report = client.post(f"/sessions/{sid}/end").json()
    assert report["questions"] == [] and report["overall_score"] == 0


def test_coding_endpoints_need_a_coding_session_owned_by_the_user(client, anon, problem):
    sid = start(client)
    other = authed(register(anon, "other@example.com"))
    assert other.get(f"/sessions/{sid}/problem").status_code == 404
    assert other.post(f"/sessions/{sid}/code/hint").status_code == 404

    text_sid = client.post("/sessions", json={**SETUP, "session_type": "technical"}).json()["session_id"]
    assert client.get(f"/sessions/{text_sid}/problem").status_code == 409
    assert client.post(f"/sessions/{text_sid}/code/run", json={"language": "python", "code": "x"}).status_code == 409


def test_deleting_session_removes_code_runs(client, problem, db):
    sid = start(client)
    client.post(f"/sessions/{sid}/code/run", json={"language": "python", "code": "x"})
    assert db.query(CodeRun).count() == 1
    assert client.delete(f"/sessions/{sid}").status_code == 204
    assert db.query(CodeRun).count() == 0


def test_pick_problem_matches_level_and_prefers_unseen(db, problem):
    from app.models import User

    hard = CodingProblem(**{**PROBLEM, "title": "Hard one", "difficulty": "hard"})
    other = CodingProblem(**{**PROBLEM, "title": "Other easy"})
    retired = CodingProblem(**{**PROBLEM, "title": "Retired", "is_active": False})
    user = User(email="p@example.com", name="P")
    db.add_all([hard, other, retired, user])
    db.commit()
    assert coding.pick_problem(db, user.id, "mid").title == "Hard one"
    db.add(InterviewSession(user_id=user.id, role="r", level="intern", problem_id=problem.id))
    db.commit()
    assert {coding.pick_problem(db, user.id, "intern").title for _ in range(10)} == {"Other easy"}


def test_correctness_score():
    run = CodeRun(status="ok", passed=2, total=2, hidden_passed=2, hidden_total=2)
    assert coding.correctness_score(run, 0) == 10
    assert coding.correctness_score(run, 2) == 8
    run.hidden_passed = 0
    assert coding.correctness_score(run, 0) == 6
    run.status = "time_limit"
    assert coding.correctness_score(run, 5) == 1


def test_seed_problems_loads_bank_once(db):
    assert coding.seed_problems(db) >= 6
    assert coding.seed_problems(db) == 0
    for p in db.query(CodingProblem):
        assert coding.check_problem_shape(p.function_name, p.params, p.tests) == []
        assert len(p.hints) == 3 and p.expected_complexity


# ---------- admin (FR-60, UC-05) ----------

@pytest.fixture
def admin(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", ["admin@example.com"])
    return authed(register(anon, "admin@example.com"))


def test_admin_problem_crud_validates_reference_solution(admin, client, fake_sandbox):
    assert client.get("/admin/problems").status_code == 403

    created = admin.post("/admin/problems", json=PROBLEM)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert fake_sandbox.calls[-1]["language"] == "python" and len(fake_sandbox.calls[-1]["tests"]) == 4

    wrong = {**PROBLEM, "reference_solution": "def add_two(a, b):\n    return a - b  # wrong\n"}
    res = admin.put(f"/admin/problems/{pid}", json=wrong)
    assert res.status_code == 422 and "Test 1: expected 3" in res.json()["error"]

    updated = admin.put(f"/admin/problems/{pid}", json={**PROBLEM, "title": "Sum of Two"})
    assert updated.json()["title"] == "Sum of Two"
    assert admin.get(f"/admin/problems/{pid}").json()["title"] == "Sum of Two"
    assert [p["id"] for p in admin.get("/admin/problems").json()] == [pid]

    assert admin.delete(f"/admin/problems/{pid}").status_code == 204
    assert admin.get(f"/admin/problems/{pid}").json()["is_active"] is False
    assert admin.get("/admin/problems/999").status_code == 404


def test_admin_problem_shape_checks(admin, fake_sandbox):
    no_hidden = {**PROBLEM, "tests": [{**t, "hidden": False} for t in PROBLEM["tests"]]}
    res = admin.post("/admin/problems", json=no_hidden)
    assert res.status_code == 422 and "hidden test" in res.json()["error"]
    bad = {**PROBLEM, "function_name": "class", "tests": [{"args": [1], "expected": 1}, *PROBLEM["tests"]]}
    err = admin.post("/admin/problems", json=bad).json()["error"]
    assert "'class' is not a valid" in err and "Test 1 has 1 arguments" in err
    assert fake_sandbox.calls == []  # static checks run before the sandbox

    fake_sandbox.next = RunResult("compile_error", message="SyntaxError")
    res = admin.post("/admin/problems", json=PROBLEM)
    assert res.status_code == 422 and "failed to run: SyntaxError" in res.json()["error"]
