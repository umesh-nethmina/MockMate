"""Follow-up relevance review (Phase 6): what does the interviewer ask after a vague or weak answer?

Relevance is a human judgement, so this writes a Markdown checklist for a reviewer instead of a score.

    cd backend
    .venv/Scripts/python -m evals.run_followup_review          # dry run with the cost estimate
    .venv/Scripts/python -m evals.run_followup_review --yes    # calls the real API (costs money)

Then open the file in evals/results/ and tick each follow-up that probes the right gap.
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.agents import interviewer
from app.agents.context import InterviewContext
from app.agents.interviewer import Turn, TurnPlan
from app.config import get_settings
from app.llm import LLMError
from app.llm.client import LLMClient
from evals.run_evaluator_eval import load

HERE = Path(__file__).parent
EST_COST_PER_ITEM = 0.015


def plan_for(case: dict) -> TurnPlan:
    """Mid-interview, follow-up allowed: the decision and the wording are entirely the interviewer's."""
    return TurnPlan(questions_asked=2, question_limit=8, round=case["round"], difficulty="medium")


def review_markdown(rows: list[dict], cost: float) -> str:
    lines = [
        f"# Follow-up relevance review ({interviewer.PROMPT}, {datetime.now(UTC):%Y-%m-%d})",
        "",
        "Tick each case where the interviewer's reply probes the gap described under *Should*. "
        f"Target: 8 of {len(rows)}. Cost of this run: ${cost:.3f}.",
        "",
    ]
    for r in rows:
        lines += [
            f"## {r['id']} · {r['role']} ({r['level']}, {r['round']})",
            f"- **Question:** {r['question']}",
            f"- **Answer:** {r['answer']}",
            f"- **Should:** {r['should']}",
        ]
        if "error" in r:
            lines.append(f"- **Error:** {r['error']}")
        else:
            lines += [
                f"- **Decision:** `{r['decision']}` · judged answer `{r['quality']}` · topic \"{r['topic']}\"",
                f"- **Interviewer:** {r['reply']}",
            ]
        lines += ["- [ ] Relevant follow-up", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    args = parser.parse_args()

    cases = load(HERE / "followup_cases.jsonl")
    print(f"{len(cases)} cases, prompt {interviewer.PROMPT}, estimated cost ≈ ${len(cases) * EST_COST_PER_ITEM:.2f}")
    if not args.yes:
        print("Dry run. Re-run with --yes to call the API.")
        return 0

    llm = LLMClient(get_settings())

    def one(case: dict) -> dict:
        ctx = InterviewContext(role=case["role"], level=case["level"], job_description="")
        transcript = [Turn("interviewer", case["question"]), Turn("candidate", case["answer"])]
        try:
            result = interviewer.next_turn(llm, ctx, transcript, plan_for(case))
        except LLMError as err:
            return {**case, "error": str(err), "cost": err.usage.cost_usd if err.usage else 0.0}
        out = result.output
        return {**case, "decision": out.decision, "quality": out.previous_answer_quality, "topic": out.topic,
                "reply": out.question, "cost": result.usage.cost_usd}

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(one, cases))
    cost = sum(r["cost"] for r in rows)
    out = HERE / "results" / f"followups-{datetime.now(UTC):%Y%m%d-%H%M%S}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(review_markdown(rows, cost), encoding="utf-8")
    print(f"Actual cost: ${cost:.3f}. Review checklist: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
