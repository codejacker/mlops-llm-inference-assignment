# Submission guide & checklist

A phase-by-phase plan derived from the README: what to do, the deliverable it
produces, **where that deliverable comes from**, and **where to put it**. Items
already done off-GPU are checked. See `BUILD.html` / `RUN.html` for the concepts.

Legend: `[x]` done · `[ ]` to do · 🖥️ needs the H100 VM · 💻 doable on your Mac

---

## Phase 0 — Setup

- [x] 💻 Repo is yours (fresh git history)
- [x] 💻 `.env` created from `.env.example`
- [x] 💻 BIRD data loaded → `data/bird/` (11 DBs, 30 eval Qs, 1500 perf Qs)
- [ ] 🖥️ On the VM: forward 5 ports (3000, 9090, 3001, 8000, 8001), `uv sync`, `docker compose up -d`
- [ ] 🖥️ Confirm 3 UIs load: Prometheus `:9090`, Grafana `:3000` (admin/admin), Langfuse `:3001`

**Deliverable:** none (environment only).

---

## Phase 1 — vLLM serving 🖥️

Steps: start vLLM with chosen flags → confirm it loads and returns sensible SQL
on 3–5 questions from `evals/eval_set.jsonl` → write the config down.

- [ ] vLLM serving Qwen3-30B at `localhost:8000`
- [ ] A few manual queries return sensible SQL
- [ ] **Deliverable:** screenshot of vLLM serving + a manual query → `screenshots/vllm_manual_query.png`
- [ ] **Deliverable:** your flags + one-line justifications → section in `REPORT.md`

*Comes from:* running `scripts/start_vllm.sh` (add your flags) and a `curl` to `:8000/v1/chat/completions`.

---

## Phase 2 — Observability dashboard 💻 build / 🖥️ verify

Steps: extend the starter dashboard to cover latency (percentiles), throughput,
KV cache, drawing metrics from vLLM `/metrics`.

- [x] 💻 Dashboard JSON written (11 panels: latency / throughput / KV cache) → `infra/grafana/provisioning/dashboards/serving.json`
- [ ] 🖥️ Every panel visibly reacts when you fire requests
- [ ] **Deliverable:** screenshot of the full dashboard reacting to a burst → `screenshots/grafana_serving.png`
- [x] **Deliverable:** dashboard JSON committed under `infra/grafana/provisioning/dashboards/`

*Comes from:* the JSON is done; the screenshot comes from Grafana on the VM under load.

---

## Phase 3 — Agent 💻

Steps: implement the LLM nodes, write prompts, wire the verify→revise loop with
an iteration cap, test interactively.

- [x] `verify`, `revise`, `route_after_verify` implemented → `agent/graph.py`
- [x] All 6 prompts written → `agent/prompts.py`
- [x] Loop wired with cap (`MAX_ITERATIONS = 3`)
- [ ] 🖥️ Run server, confirm ≥1 question triggers a revise (final tuning on real Qwen3)
- [x] **Deliverable:** implemented `agent/graph.py` + `agent/prompts.py` (in repo)

*Comes from:* the code is done; the "triggers a revise" check is observed at run time (see it in `history` or in Langfuse).

---

## Phase 4 — Agent tracing (Langfuse) 🖥️ (or 💻 with a key)

Steps: create a local Langfuse project, grab keys → `.env`, fire 10 questions,
inspect a trace, tag traces with metadata.

- [ ] Sign up at `localhost:3001`, create project, copy public + secret keys
- [ ] Paste keys into `.env` (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`)
- [ ] Fire 10 questions; confirm the generate/verify/(revise) waterfall appears
- [ ] **Deliverable:** screenshot of one trace's waterfall → `screenshots/langfuse_trace.png`
- [ ] **Deliverable:** screenshot of the trace list with your tags → `screenshots/langfuse_tags.png`

*Comes from:* the Langfuse hook is already wired in `agent/server.py`; just supply keys and tags. Pass tags via the `/answer` request body's `tags` field.

---

## Phase 5 — Evals 💻 logic / 🖥️ real numbers

Steps: implement the eval runner (execution accuracy + per-iteration pass rate),
run baseline, read whether the loop earns its keep.

- [x] `eval_one` + `summarize` implemented → `evals/run_eval.py`
- [ ] 🖥️ Run baseline against the 30B endpoint
- [ ] **Deliverable:** baseline results (overall + per-iteration pass rate) → `results/eval_baseline.json`
- [ ] **Deliverable:** screenshot of Grafana while the eval runs → `screenshots/grafana_eval_run.png`
- [ ] Note in `REPORT.md`: is the loop doing real work? (compare iter-0 vs last)

*Comes from:* `uv run python evals/run_eval.py --out results/eval_baseline.json` (writes the JSON itself).

---

## Phase 6 — SLO diagnosis & iteration 🖥️ (highest weight, 25%)

Target: **P95 end-to-end agent latency < 5s at 10+ RPS over 5 min.**
Steps: load test → diagnose from the dashboard → change one thing → re-measure →
log it → re-eval to check quality survived.

- [ ] Run `uv run python load_test/driver.py --rps 10 --duration 300`, watch Grafana
- [ ] **Deliverable:** before/after screenshots of the change that moved the needle → `screenshots/grafana_before.png`, `screenshots/grafana_after.png`
- [ ] **Deliverable:** post-tuning eval → `results/eval_after_tuning.json` (re-run the eval, change `--out`)
- [ ] **Deliverable:** iteration log "saw X → hypothesized Y → changed Z → result W" → section in `REPORT.md`
- [ ] Honest verdict: SLO hit, or missed with the gap quantified → `REPORT.md`

*Comes from:* the load driver + dashboard; each iteration = one note + one screenshot.

---

## Phase 7 — Report 💻

- [ ] **Deliverable:** `REPORT.md` (≤ 3 pages) with: 1) serving config + justification, 2) baseline eval (overall + per-iteration), 3) SLO cycle (baseline vs SLO, iteration log, final numbers), 4) agent value paragraph (cite per-iteration pass rate), 5) what you'd do with more time (specific).

---

## Master deliverables checklist (the grader's table)

| Deliverable | Phase | Where it lives | Status |
|---|---|---|---|
| `agent/graph.py`, `agent/prompts.py` | 3 | repo | [x] done |
| `evals/run_eval.py` | 5 | repo | [x] done |
| `infra/grafana/provisioning/dashboards/serving.json` | 2 | repo | [x] done |
| `results/eval_baseline.json` | 5 | written by eval runner | [ ] 🖥️ |
| `results/eval_after_tuning.json` | 6 | written by eval runner (`--out`) | [ ] 🖥️ |
| `screenshots/vllm_manual_query.png` | 1 | save manually | [ ] 🖥️ |
| `screenshots/grafana_serving.png` | 2 | save manually | [ ] 🖥️ |
| `screenshots/langfuse_trace.png` | 4 | save manually | [ ] 🖥️ |
| `screenshots/langfuse_tags.png` | 4 | save manually | [ ] 🖥️ |
| `screenshots/grafana_eval_run.png` | 5 | save manually | [ ] 🖥️ |
| `screenshots/grafana_before.png` | 6 | save manually | [ ] 🖥️ |
| `screenshots/grafana_after.png` | 6 | save manually | [ ] 🖥️ |
| `REPORT.md` | 1,5,6,7 | write as you go | [ ] |

`results/` and `screenshots/` already exist (with `.gitkeep`). Note `.gitignore`
ignores `results/*.json` and `screenshots/*.png` — when you have the real
deliverables, force-add them: `git add -f results/*.json screenshots/*.png`.

---

## Final submission

1. [ ] All rows in the master table present.
2. [ ] `REPORT.md` complete (≤ 3 pages, honest about misses).
3. [ ] Force-add the gitignored deliverables, commit, push.
4. [ ] Submit your repo URL.
