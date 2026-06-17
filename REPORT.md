# REPORT — LLM inference + observability

*Text-to-SQL PoC on Qwen3-30B-A3B (vLLM, 1× H100) with a LangGraph verify/revise
agent. Target SLO: P95 end-to-end agent latency < 5s at 10+ RPS over 5 minutes.*

> Fill the `<...>` placeholders as you complete each GPU phase. Keep it ≤ 3 pages.

---

## 1. Serving configuration (Phase 1)

Model: `Qwen/Qwen3-30B-A3B-Instruct-2507` · Hardware: 1× H100 80GB.

Workload profile: ~1.5–3K-token prompts, short structured (SQL) outputs, ~2–3
dependent LLM calls per user request.

| Flag | Value | One-line justification |
|---|---|---|
| `--max-model-len` | `<e.g. 4096>` | `<cap context to real prompt+output size → more KV headroom>` |
| `--gpu-memory-utilization` | `<e.g. 0.90>` | `<give KV cache room on the 80GB card>` |
| `--max-num-seqs` | `<e.g. 256>` | `<concurrency ceiling; throughput vs latency dial>` |
| `<quantization, if used>` | `<e.g. fp8>` | `<free memory for KV cache on a 30B MoE>` |
| `<other>` | `<...>` | `<...>` |

Notes on the MoE / prompt-shape tradeoff: `<why these levers for an A3B MoE with
long prompts and short outputs>`

---

## 2. Baseline eval results (Phase 5)

Run: `uv run python evals/run_eval.py --out results/eval_baseline.json` against
the real 30B endpoint. 30 questions, execution accuracy (canonicalized row sets).

- Overall pass rate: `<x>%`
- Pass rate by iteration (carry-forward): iter0 `<a>%` → iter1 `<b>%` → iter2 `<c>%`
- Avg iterations per question: `<n>`

Commentary: `<does the loop earn its keep? compare iter0 vs final>`

---

## 3. Hitting the SLO (Phase 6)

Target: **P95 < 5s at 10+ RPS over 5 min.**
Run: `uv run python load_test/driver.py --rps 10 --duration 300`.

**Baseline vs SLO**

| Metric | Baseline | SLO | Hit? |
|---|---|---|---|
| Achieved RPS | `<...>` | 10+ | `<y/n>` |
| P95 latency | `<...>s` | < 5s | `<y/n>` |
| P99 latency | `<...>s` | — | — |

**Iteration log** (saw X → hypothesized Y → changed Z → result W)

1. saw `<metric moved first>` → hypothesized `<cause>` → changed `<one flag>` → result `<what happened to that metric AND to P95>`
2. saw `<...>` → hypothesized `<...>` → changed `<...>` → result `<...>`
3. `<...>`

Screenshots: `screenshots/grafana_before.png`, `screenshots/grafana_after.png`.

**Final numbers**

| Metric | Final |
|---|---|
| Achieved RPS | `<...>` |
| P95 latency | `<...>s` |
| Post-tuning overall pass rate | `<...>%` (see `results/eval_after_tuning.json`) |

Did quality survive the tuning? `<yes/no + analysis if it regressed>`

---

## 4. Agent value

`<One paragraph. Did the verify/revise loop actually help? How do you know? Cite
the per-iteration pass rate from §2: if iter0 ≈ final, the loop is decoration; if
final is meaningfully higher, it earns its keep. Mention an example question that
was wrong at iter0 and correct after a revise.>`

---

## 5. What I'd do with more time

`<Be specific — not "add Kubernetes". Examples to make concrete: schema-linking /
column pruning to shrink prompts; few-shot examples in the generate prompt;
speculative decoding or prefix caching for the repeated schema; a cheaper verify
(skip the LLM when SQL errors or returns 0 rows); batching the eval; an
LLM-as-judge for partial credit.>`

---

### Verdict

`<SLO hit, or missed with the gap quantified. A metric-grounded miss is fine —
state what you'd change next.>`
