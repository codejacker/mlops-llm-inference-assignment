"""Eval runner using execution accuracy.

Reads evals/eval_set.jsonl, calls the agent at AGENT_URL on each question,
then compares the agent's SQL output to the gold SQL by *executed rows*
(canonicalized: sorted, stringified, None-coerced to empty).

Helpers (run_sql / canonicalize / matches) are provided. You implement
eval_one() and summarize().

Run:
    uv run python evals/run_eval.py --out results/eval_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
DEFAULT_OUT_FILE = ROOT / "results" / "eval_baseline.json"
DB_DIR = ROOT / "data" / "bird"
AGENT_URL_DEFAULT = "http://localhost:8001/answer"


# ---------- Helpers (provided) -----------------------------------------

def run_sql(db_id: str, sql: str, timeout: float = 5.0) -> tuple[bool, list[tuple] | None, str | None]:
    """Run sql against db_id in read-only mode. Returns (ok, rows, error)."""
    path = DB_DIR / f"{db_id}.sqlite"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return True, rows, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"


def canonicalize(rows: list[tuple] | None) -> list[tuple] | None:
    """Sort rows; coerce cells to str; None -> ''."""
    if rows is None:
        return None
    return sorted(tuple("" if c is None else str(c) for c in row) for row in rows)


def matches(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    return canonicalize(gold_rows) == canonicalize(pred_rows)


# ---------- Implement these (Phase 5) ----------------------------------

def eval_one(question: dict, agent_url: str) -> dict:
    """Score one question. Return a dict capturing per-iteration correctness."""
    db_id = question["db_id"]
    gold_sql = question["gold_sql"]

    # 1. Ask the agent over HTTP. On any transport/HTTP failure, record it and
    #    score the question as incorrect rather than crashing the whole run.
    t0 = time.monotonic()
    try:
        resp = httpx.post(
            agent_url,
            json={"question": question["question"], "db": db_id},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return {
            "db_id": db_id,
            "question": question["question"],
            "error": f"{type(e).__name__}: {e}",
            "n_iterations": 0,
            "per_iteration_correct": [],
            "final_correct": False,
            "final_sql": "",
            "latency_seconds": time.monotonic() - t0,
        }

    # 2. The agent returns its history. Each generate/revise step appended a
    #    {"node": ..., "sql": ...} entry, so the SQL it served at iteration k is
    #    the k-th history entry that carries a "sql" key.
    history = data.get("history", [])
    iter_sqls = [h["sql"] for h in history if "sql" in h]

    # 3. Gold rows = ground truth. Run the curated gold SQL once.
    gold_ok, gold_rows, gold_err = run_sql(db_id, gold_sql)

    # 4. Execution accuracy at EACH iteration: run that iteration's SQL and
    #    compare canonicalized row sets to gold. matches() handles sorting /
    #    stringifying / None->''.
    per_iter = []
    for sql in iter_sqls:
        ok, rows, _ = run_sql(db_id, sql)
        per_iter.append(bool(ok and gold_ok and matches(gold_rows, rows)))

    return {
        "db_id": db_id,
        "question": question["question"],
        "n_iterations": len(iter_sqls),
        "per_iteration_correct": per_iter,
        "final_correct": per_iter[-1] if per_iter else False,
        "final_sql": data.get("sql", ""),
        "gold_error": gold_err,  # non-null means the gold SQL itself failed
        "latency_seconds": time.monotonic() - t0,
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate per-question results.

    Per-iteration carry-forward: if the agent terminated at iteration j < k
    (verify said ok at j, or it hit MAX_ITERATIONS at j < k), treat the
    question's iteration-k result as identical to its iteration-j result.
    The agent stopped emitting; whatever it had at termination is what
    would have been served had we polled at iteration k.
    """
    n = len(results)
    if n == 0:
        return {"n": 0}

    overall = sum(1 for r in results if r["final_correct"]) / n

    # k_max = the most iterations any single question took. We report a pass rate
    # for each iteration index 0..k_max-1.
    k_max = max((r["n_iterations"] for r in results), default=0)

    pass_rate_by_iteration = []
    for k in range(k_max):
        correct = 0
        for r in results:
            per_iter = r["per_iteration_correct"]
            if not per_iter:
                continue  # agent produced nothing -> incorrect at every k
            # Carry-forward: a question that stopped at j < k contributes its
            # last (terminal) result, because that's what would have been served.
            idx = k if k < len(per_iter) else len(per_iter) - 1
            correct += int(per_iter[idx])
        pass_rate_by_iteration.append(round(correct / n, 4))

    return {
        "n": n,
        "overall_pass_rate": round(overall, 4),
        # pass_rate_by_iteration[0] = "if we stopped after generate (iter 0)".
        # Compare first vs. last: if they're equal, the verify/revise loop is
        # doing nothing. If the last is higher, the loop earns its keep.
        "pass_rate_by_iteration": pass_rate_by_iteration,
        "avg_iterations": round(sum(r["n_iterations"] for r in results) / n, 2),
        "errors": sum(1 for r in results if r.get("error")),
    }


# ---------- Main (provided) --------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_FILE)
    parser.add_argument("--agent-url", default=AGENT_URL_DEFAULT)
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.eval_set.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(questions)} eval questions from {args.eval_set}")

    results: list[dict] = []
    t0 = time.monotonic()
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['db_id']}: {q['question'][:60]}...", flush=True)
        results.append(eval_one(q, args.agent_url))
    elapsed = time.monotonic() - t0

    summary = summarize(results)
    out = {
        "summary": summary,
        "wall_clock_seconds": elapsed,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
