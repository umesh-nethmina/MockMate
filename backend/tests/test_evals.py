"""The eval set is well-formed and the agreement maths is right. Never calls the API."""

from evals import run_evaluator_eval as ev


def test_eval_set_is_well_formed():
    items = ev.load(ev.HERE / "evaluator_set.jsonl")
    assert len(items) == 30
    assert len({i["id"] for i in items}) == 30
    for i in items:
        assert i["round"] in ("hr", "technical") and i["level"] in ("intern", "junior", "mid")
        assert all(1 <= i["expected"][d] <= 10 for d in ev.DIMENSIONS), i["id"]
        assert i["question"] and i["answer"] and i["note"]
    # covers the whole scale, both rounds, and the adversarial cases
    assert {i["round"] for i in items} == {"hr", "technical"}
    averages = [sum(i["expected"].values()) / 3 for i in items]
    assert min(averages) <= 2 and max(averages) >= 9
    assert any("10/10" in i["answer"] for i in items)


def test_agreement_and_summary():
    a = ev.agreement({"correctness": 7, "clarity": 7, "depth": 7}, {"correctness": 8, "clarity": 6, "depth": 7})
    assert a["within"] and a["diffs"] == {"correctness": 1, "clarity": -1, "depth": 0}
    b = ev.agreement({"correctness": 7, "clarity": 7, "depth": 7}, {"correctness": 9, "clarity": 7, "depth": 7})
    assert not b["within"]
    rows = [a] * 4 + [b] + [{"error": "x"}]
    s = ev.summarise(rows)
    assert (s["items"], s["scored"], s["within_tolerance"], s["agreement"], s["passed"]) == (6, 5, 4, 0.8, True)
    assert s["mean_bias"]["correctness"] == 1.2  # (4 × 1 + 2) / 5
    assert s["mean_abs_error"]["clarity"] == 0.8


def test_followup_review_markdown():
    from evals import run_followup_review as fr

    cases = fr.load(fr.HERE / "followup_cases.jsonl")
    assert len(cases) == 10 and all(c["should"] for c in cases)
    assert fr.plan_for(cases[0]).follow_up_allowed
    rows = [{**cases[0], "decision": "follow_up", "quality": "weak", "topic": "Generators", "reply": "Why?"},
            {**cases[1], "error": "boom"}]
    md = fr.review_markdown(rows, 0.03)
    assert md.count("- [ ] Relevant follow-up") == 2 and "`follow_up`" in md and "**Error:** boom" in md


def test_dry_run_makes_no_calls(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["eval", "--limit", "3"])
    monkeypatch.setattr(ev, "LLMClient", lambda *a: (_ for _ in ()).throw(AssertionError("no API in dry run")))
    assert ev.main() == 0
    assert "3 answers" in capsys.readouterr().out
