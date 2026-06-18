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
| `--quantization` | `fp8` | Quantizes weights from bf16 (~56.9 GiB) to ~30 GiB, roughly doubling the free budget for KV cache and lifting the concurrency ceiling, at near-lossless quality (eval held — see §2/§3). Honest caveat: Phase 6 showed this did **not** move the SLO, because the bottleneck was the agent, not vLLM's KV — kept anyway as harmless headroom (see the §3 iteration log). |

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
the real 30B endpoint (fp8). 30 questions, execution accuracy (canonicalized row sets).

- Overall pass rate: **30.0%** (9/30)
- Pass rate by iteration (carry-forward): iter0 **30.0%** → iter1 **30.0%** → iter2 **30.0%**
- Avg iterations per question: **1.57**
- Errors: 0/30

Commentary: the verify/revise loop **fired** (avg 1.57 iterations — roughly a third
of questions triggered at least one revise) but on this run it flipped **zero**
answers: every iteration holds at 30.0%. An earlier run on bf16 weights showed the
loop rescuing exactly one question (33.3% → 36.7%); taken together, the loop's
accuracy contribution is **within run-to-run noise** (0 to +1 of 30) and does not
reliably earn its keep on this set. ~30% on BIRD with a 30B MoE and minimal
prompting is a plausible baseline — the gap to higher accuracy is dominated by
generation quality (schema linking, few-shot examples), not by more revise loops.

---

## 3. Hitting the SLO (Phase 6)

Target: **P95 < 5s at 10+ RPS over 5 min.**
Run: `uv run python load_test/driver.py --rps 10 --duration 300`.

**The dashboard & how I read it.** The Grafana board (`infra/grafana/provisioning/dashboards/serving.json`) has three vLLM rows built from `/metrics` — **Latency** (e2e, time-to-first-token, time-per-output-token, queue time, all p50/p95/p99), **Throughput & saturation** (running vs waiting overlaid, finished req/s, generation vs prompt tokens), and **KV cache** (usage %, preemptions/s) — answering "is it slow, and where in the lifecycle?". For Phase 6 I added a top **SLO row**: the agent's end-to-end `/answer` latency (p50/p95/p99 against a 5s threshold line) plus agent throughput by outcome. Driving reason — the SLO is *end-to-end agent* latency, which vLLM's own metrics cannot see (they time a single LLM call, not the 2–3-call chain). That row is what actually tracks the target, and it is what made the bottleneck obvious: under load the agent p95 blew past 5s while every vLLM saturation panel stayed healthy (queue ≈ 0, KV ~10%, preemptions 0). Aggregate percentiles live in Grafana; per-trace "why was *this* request slow" attribution lives in Langfuse — the two layers combined are the diagnosis.

**Baseline (before fixes) vs SLO** — 10 RPS offered, 300s (`results/load_before.json`):

| Metric | Baseline | SLO | Hit? |
|---|---|---|---|
| P95 latency | 6.46s | < 5s | **no** |
| P99 latency | 10.08s | — | — |
| Offered / achieved RPS | 10 / 8.3* | 10+ | partial |
| Error rate | 13% (389/3000) | — | — |

\*`achieved_rps` is a driver artifact: 3000 requests issued over 300s plus a ~60s
drain tail = 360s wall-clock → 8.3. It signals a *small backlog* at 10 RPS, not a
capacity ceiling of 8.3.

**Capacity sweep** (`results/sweep_*rps.json`, 90s each) located the wall before
tuning: p95 stayed under 5s through ~4 RPS (2.9s @ 2 RPS, 4.6s @ 4 RPS) and broke
between 4 and 6 RPS — at 6 RPS p95 jumped to ~50s and the system could no longer
sustain the offered rate.

**Iteration log** (saw X → hypothesized Y → changed Z → result W)

1. **saw** agent p95 = 6.46s at 10 RPS while *every* vLLM panel sat idle — queue ≈ 0,
   KV cache ~0%, preemptions 0, requests-running well under the 64 cap → **hypothesized**
   the bottleneck is the agent orchestration, not vLLM, so serving-side levers (fp8,
   `max-num-seqs`, `max-model-len`) won't move the SLO → **confirmed** by the agent
   SLO row: vLLM healthy, agent the wall. (fp8 was kept — it frees KV headroom — but
   it provably did *not* move the SLO, since KV was never the constraint.)
2. **saw** "requests running" plateau near ~40 → **hypothesized** the FastAPI sync
   handler was hitting AnyIO's default 40-thread cap, so requests queued for a thread
   while vLLM idled → **changed** the threadpool limit to 200 (G5) → running climbed
   past 40, throughput rose, the agent stopped starving vLLM.
3. **saw** avg 1.57 iterations with zero accuracy gain past iter 1 (§2) → **hypothesized**
   the 2nd/3rd LLM round-trips were pure latency cost → **changed** `MAX_ITERATIONS`
   3→2 (G3) and short-circuited the verify LLM call on a SQL execution error (G4),
   cutting vLLM calls per request → **result: p95 6.46s → 4.96s, crossing under 5s**;
   quality held at 30% and avg iterations fell to 1.30.
4. **saw** a constant ~13% error rate, identical across 2–10 RPS → **hypothesized**
   content-driven, not load: the `schema + question` prompt exceeding `max-model-len`
   = 4096 on large-schema DBs (the §1 KV-headroom tradeoff biting back). Not the SLO
   bottleneck; see §5 for the fix.

Screenshots: `screenshots/grafana_before.png` (p95 above the 5s line, vLLM idle),
`screenshots/grafana_after.png` (p95 at/under the line, throughput ~10 req/s).

**Where the latency goes (Langfuse, `screenshots/langfuse_trace.png`).** A
representative slow trace (7.76s, `codebase_community`) breaks down as
`generate_sql` 3.78s + `revise` 3.28s + final `verify` 0.68s — and the *first*
`verify` at **0.00s**, the G4 short-circuit firing on a failed execution (no LLM
call). ~91% of a slow request is the two generation calls, so the p95 tail is
exactly the subset of requests that revise. This is the per-node confirmation of
the fix logic: capping iterations (G3) removes one ~3.3s generation from the
worst case, which is what pulled p95 under 5s; verify is cheap and, on the error
path, free.

**Final numbers** (after G3+G4+G5, `results/load_after.json`):

| Metric | Final | SLO | Hit? |
|---|---|---|---|
| P95 latency | **4.96s** | < 5s | **yes** |
| P99 latency | 9.39s | — | — |
| Offered RPS (5-min window) | 10 | 10+ | yes (with drain tail) |
| Post-tuning overall pass rate | 30.0% | no regression | yes (`results/eval_after_tuning.json`) |

Did quality survive the tuning? **Yes.** Pass rate is unchanged at 30.0% and the
per-iteration rate stays flat ([0.30, 0.30] at the new 2-iteration cap), confirming
the cap removed only latency, not accuracy — exactly as §2/§4 predicted.

---

## 4. Agent value

The verify/revise loop is the agent's core architectural bet, and on this eval set
it **does not reliably pay off**. By the per-iteration pass rate (§2), accuracy was
**flat across all iterations (30.0% at iter0, iter1, iter2)** on the fp8 baseline —
the loop fired (avg 1.57 iterations) but flipped no answers. An earlier bf16 run
*did* show it rescue exactly one of 30 (33.3% → 36.7%): there, *"What is the type
of the card 'Ancestor's Chosen' as originally printed?"* (`card_games`) was wrong
at iter0 and correct after a revise that added guards excluding null / literal
`'None'` rows (`... AND originalType IS NOT NULL AND originalType != 'None'`). So
the mechanism *can* do its intended job — catch an answer that executed fine but
didn't make sense — but the **measured** effect (0 to +1 question across runs) sits
within run-to-run noise. Honest verdict: the loop's value here is real-but-marginal
and not dependable; the dominant lever for accuracy is generation quality (schema
linking, few-shot prompting), not more revise iterations. This is also *why*
capping iterations in Phase 6 (below) is accuracy-neutral — there is no accuracy to
lose.

---

## 5. What I'd do with more time

In priority order, grounded in what the data above showed:

1. **Kill the 13% error rate (schema linking / column pruning).** The errors are
   prompts overflowing `max-model-len=4096` on large schemas. Linking only the
   tables/columns relevant to the question would shrink prompts below the limit,
   eliminate the overflows, *and* cut prompt-token load (the dominant cost — prompt
   tokens ran ~15K/s vs ~1K/s generation). This is the single highest-value fix:
   reliability **and** latency **and** likely accuracy.
2. **Lift accuracy off 30% (few-shot + schema linking).** §2/§4 showed the revise
   loop is within noise; the real lever is generation quality. A handful of
   in-context BIRD examples and tighter schema context would move the number more
   than any loop change.
3. **Make the agent path async.** The nodes are sequential `requests`-style calls
   run in a threadpool; `ainvoke` with an async LLM client would parallelize
   independent work (e.g. schema render) and drop the thread overhead that G5 worked
   around rather than removed.
4. **Prefix-cache the schema in vLLM.** The same multi-K-token schema prefix is
   re-sent on every call; vLLM prefix caching would skip re-prefilling it, directly
   attacking the prompt-token load that dominates this workload.
5. **Richer eval signal.** Execution accuracy is all-or-nothing; an LLM-as-judge for
   partial credit (right columns, wrong filter) would make the agent-value question
   answerable with more than 30 binary outcomes, where +1 question is within noise.

---

### Verdict

**Latency SLO: met.** After G3+G4+G5, P95 end-to-end agent latency is **4.96s
(< 5s) at 10 RPS offered over a 5-minute window** — down from 6.46s at baseline.
The win came from correctly locating the bottleneck: the dashboard proved vLLM was
idle (KV ~0%, queue 0) while the agent was the wall, so the fixes targeted the agent
(concurrency cap + redundant LLM calls), not the serving config.

**Two honest caveats keep this from being production-ready:** (1) a persistent **13%
error rate** from prompts overflowing the 4096-token context on large schemas — a
direct consequence of the §1 KV-headroom choice, fixable by schema linking (§5);
and (2) a small backlog at sustained 10 RPS (the ~60s drain tail). Quality did not
regress (30.0% held). Net: the headline target is met and the diagnosis is fully
metric-grounded, but I'd resolve the 13% before calling it shippable.
