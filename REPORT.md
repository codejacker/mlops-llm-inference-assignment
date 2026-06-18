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
| `--max-model-len` | `4096` | Default is 262144 (256K); holding one request at that length needs 24 GiB KV cache but only ~8.7 GiB is free → engine refuses to start. Prompts are ~3K tokens, so 4096 covers them and frees the KV pool for concurrency. |
| `--gpu-memory-utilization` | `0.92` | Weights take 56.9 GiB of the 80 GiB card. At 0.92 the budget is 73.6 GiB → ~10–11 GiB left for KV cache after overhead, up from 8.7 GiB at the 0.90 default. |
| `--max-num-seqs` | `64` | Concurrency ceiling. Starting value; the throughput-vs-latency dial tuned in Phase 6 against the SLO. |
| `--trust-remote-code` | `(flag)` | Qwen3's tokenizer ships custom code; without it vLLM falls back to the slow `Qwen2Tokenizer`, which crashes on `all_special_tokens_extended`. |
| quantization | none (bf16) | Weights at bf16 (56.9 GiB) leave enough room for KV at 4096 context; fp8 was unnecessary for this prompt shape. Revisit if more concurrency is needed. |

Notes on the MoE / prompt-shape tradeoff: Qwen3-30B-A3B is an MoE — 30B total
params on disk (~57 GiB at bf16) but only ~3B active per token, so it is
**memory-bound, not compute-bound**. The binding constraint on one H100 is the
KV-cache budget left after the full weights load, not FLOPs. With long-ish
prompts (schema + question) and short SQL outputs, the highest-leverage knob is
`--max-model-len`: shrinking the context window directly multiplies how many
requests fit in the KV pool. `--gpu-memory-utilization` is the secondary lever,
and `--max-num-seqs` caps tail latency under load.

---

## 2. Baseline eval results (Phase 5)

Run: `uv run python evals/run_eval.py --out results/eval_baseline.json` against
the real 30B endpoint. 30 questions, execution accuracy (canonicalized row sets).

- Overall pass rate: **36.67%** (11/30)
- Pass rate by iteration (carry-forward): iter0 **33.33%** → iter1 **36.67%** → iter2 **36.67%**
- Avg iterations per question: **1.53**
- Errors: 0/30

Commentary: the verify/revise loop fixed **exactly one question** (33.33% → 36.67%,
i.e. +1/30 = +3.33pp). The **third iteration added nothing** (36.67% → 36.67%), so
in this baseline the loop's value comes entirely from a single revise pass; a cap
of 2 iterations would have captured all the benefit. The loop earns a *modest but
real* keep rather than a dramatic one. ~37% on BIRD with a 30B MoE and minimal
prompting is a plausible baseline — the gap to higher accuracy is dominated by
generation quality (schema linking, few-shot examples), not by more revise loops.

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

The verify/revise loop helped, modestly and measurably. By the per-iteration pass
rate (§2), accuracy rose from **33.33% at iter0 to 36.67% after one revise** — the
loop rescued exactly one of 30 questions, and the third iteration added nothing,
so the entire benefit is one successful revise pass. Concrete example: *"What is
the type of the card 'Ancestor's Chosen' as originally printed?"* (`card_games`)
was **wrong at iter0 and correct after a revise** (`per_iteration_correct:
[False, True]`). The first generation returned a value that didn't answer the
question (a null / literal `'None'` originalType); the verifier flagged the result
as implausible, and the revise produced:

```sql
SELECT DISTINCT originalType FROM cards
WHERE name = 'Ancestor''s Chosen'
  AND originalType IS NOT NULL AND originalType != 'None';
```

i.e. it added the guards that exclude the meaningless rows. This is the loop doing
exactly its intended job — catching an answer that *executed fine but didn't make
sense* — which a single generate-only pass cannot do. The honest caveat: at +3.3pp
on this set the architecture's value is real but small, and the dominant lever for
higher accuracy is generation quality (schema linking, few-shot prompting), not
more revise iterations.

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
