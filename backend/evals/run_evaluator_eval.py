"""Evaluator eval (Phase 6): does Claude's scoring agree with human reference scores?

Target from the plan: at least 80% of answers scored within ±1 of the reference on every dimension.

    cd backend
    .venv/Scripts/python -m evals.run_evaluator_eval            # dry run: shows the plan and the cost estimate
    .venv/Scripts/python -m evals.run_evaluator_eval --yes      # calls the real API (costs money)

Needs ANTHROPIC_API_KEY. It is never run by the test suite. Results go to evals/results/.
The reference scores in evaluator_set.jsonl are a first draft: review them with a second person before
treating the agreement number as meaningful.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.agents import evaluator
from app.agents.context import InterviewContext
from app.config import get_settings
from app.llm import LLMError
from app.llm.client import LLMClient

HERE = Path(__file__).parent
DIMENSIONS = ("correctness", "clarity", "depth")
TOLERANCE = 1
TARGET = 0.80
EST_COST_PER_ITEM = 0.02  # rough: ~1.5k input + ~600 output tokens on Opus 5.5, including thinking


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def agreement(expected: dict, got: dict) -> dict:
    diffs = {d: got[d] - expected[d] for d in DIMENSIONS}
    return {"diffs": diffs, "within": all(abs(v) <= TOLERANCE for v in diffs.values())}


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if "diffs" in r]
    within = sum(r["within"] for r in scored)
    per_dim = {
        d: round(sum(abs(r["diffs"][d]) for r in scored) / len(scored), 2) if scored else None for d in DIMENSIONS
    }
    bias = {d: round(sum(r["diffs"][d] for r in scored) / len(scored), 2) if scored else None for d in DIMENSIONS}
    return {
        "items": len(rows),
        "scored": len(scored),
        "within_tolerance": within,
        "agreement": round(within / len(scored), 3) if scored else 0.0,
        "target": TARGET,
        "passed": bool(scored) and within / len(scored) >= TARGET,
        "mean_abs_error": per_dim,
        "mean_bias": bias,  # positive = Claude scores higher than the reference
    }


def run(items: list[dict], workers: int) -> tuple[list[dict], float]:
    llm = LLMClient(get_settings())  # the real client, never the demo fake

    def one(item: dict) -> dict:
        ctx = InterviewContext(role=item["role"], level=item["level"], job_description="")
        try:
            result = evaluator.score_answer(llm, ctx, item["question"], item["answer"], item["round"])
        except LLMError as err:
            return {**item, "error": str(err), "cost": err.usage.cost_usd if err.usage else 0.0}
        got = {d: getattr(result.output, d) for d in DIMENSIONS}
        return {**item, "got": got, **agreement(item["expected"], got), "feedback": result.output.feedback,
                "cost": result.usage.cost_usd}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, items))
    return rows, sum(r["cost"] for r in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    parser.add_argument("--limit", type=int, default=None, help="only the first N items")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    items = load(HERE / "evaluator_set.jsonl")[: args.limit]
    estimate = len(items) * EST_COST_PER_ITEM
    print(f"{len(items)} answers, prompt {evaluator.ANSWER_PROMPT}, estimated cost ≈ ${estimate:.2f}")
    if not args.yes:
        print("Dry run. Re-run with --yes to call the API.")
        return 0

    rows, cost = run(items, args.workers)
    summary = summarise(rows)
    out = HERE / "results" / f"evaluator-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "cost_usd": round(cost, 4), "rows": rows}, indent=1,
                              ensure_ascii=False), encoding="utf-8")

    for r in rows:
        if "error" in r:
            print(f"  {r['id']}: ERROR {r['error']}")
        elif not r["within"]:
            print(f"  {r['id']}: expected {r['expected']} got {r['got']}  ({r['note']})")
    print(json.dumps(summary, indent=1))
    print(f"Actual cost: ${cost:.3f}. Details: {out}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
