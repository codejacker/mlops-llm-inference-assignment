# Submission guide & checklist (exact steps)

Phase-by-phase plan from the README, with the **exact commands** for both
machines, what each deliverable **is and where it comes from**, and where to put
it. Concepts live in `BUILD.html` / `RUN.html`.

Legend: `[x]` done · `[ ]` to do · 💻 = on your Mac · 🖥️ = on the Nebius VM

---

## The two machines

| | 💻 Your Mac | 🖥️ Nebius VM (1× H100) |
|---|---|---|
| Role | edit code, build/debug agent off-GPU | serve vLLM, get real latency + pass rates |
| LLM backend | OpenAI API (a key) — optional | local vLLM on the H100 |
| Deps | `requirements-dev.txt` (no vllm) | `uv sync` (with vllm) |
| Already set up | `.venv-dev`, BIRD data, agent verified | nothing yet |

The **same repo** runs on both. Push from one, pull on the other. Only the LLM
backend differs (set via `.env`).

---

## Part A — Provision & connect to the Nebius VM 🖥️

Console: https://console.nebius.com/project-e00xjwkcpr00g4bffh44de/compute

1. **Create an SSH key on your Mac** (if you don't have one):
   ```bash
   ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519 -C "edenl14@gmail.com"
   cat ~/.ssh/id_ed25519.pub      # copy this line
   ```
2. **Create the VM** in the console → *Compute* → *Create virtual machine*:
   - Platform / preset: a GPU platform with **1× H100** (e.g. `gpu-h100-sxm`, 1 GPU).
   - Image: an **Ubuntu + CUDA** image (so NVIDIA drivers are preinstalled). Verify `nvidia-smi` works after boot.
   - Disk: ≥ 200 GB (the Qwen3-30B weights are large).
   - SSH key: paste your `id_ed25519.pub`. Default user is usually `ubuntu`.
   - Create, then copy the VM's **public IP** from the VM details page.
3. **Connect with all five ports forwarded** (run on your Mac, keep it open):
   ```bash
   ssh -L 3000:localhost:3000 \
       -L 9090:localhost:9090 \
       -L 3001:localhost:3001 \
       -L 8000:localhost:8000 \
       -L 8001:localhost:8001 \
       ubuntu@<VM_PUBLIC_IP>
   ```
   *Logic:* the VM's UIs listen on its `localhost`; `-L` tunnels your laptop's
   ports to them so `http://localhost:3000` in your browser hits Grafana on the VM.
4. **Verify the GPU**: `nvidia-smi` → should list one H100.

> Stop the VM in the console when not in use — H100 time is billed by the hour.

---

## Part B — One-time setup

### 💻 On your Mac (already done — for reference)
```bash
cp .env.example .env
uv venv .venv-dev --python 3.12
uv pip install --python .venv-dev -r requirements-dev.txt
python3 scripts/load_data.py            # pure stdlib, no GPU
```

### 🖥️ On the VM (do this after connecting)
```bash
# install prerequisites if the image lacks them
sudo apt-get update && sudo apt-get install -y python3-dev git docker.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker     # run docker without sudo
curl -LsSf https://astral.sh/uv/install.sh | sh    # install uv
source ~/.bashrc

git clone https://github.com/codejacker/mlops-llm-inference-assignment
cd mlops-llm-inference-assignment
uv sync                                  # installs vllm + everything
cp .env.example .env
uv run python scripts/load_data.py       # BIRD data on the VM too
docker compose up -d                     # Prometheus + Grafana + Langfuse
docker compose ps                        # all services should be "running"/"healthy"
```
**Deliverable:** none (environment). **Logic:** `uv sync` gives you vllm (Linux+CUDA
only); `docker compose up` brings up both observability stacks; `load_data.py`
puts the sqlite DBs + the 30 graded questions under `data/bird/`.

- [x] 💻 Mac env + data ready
- [ ] 🖥️ VM env + data + docker stack up
- [ ] 🖥️ 3 UIs load via the tunnel: Prometheus `:9090`, Grafana `:3000` (admin/admin), Langfuse `:3001`

---

## Phase 1 — vLLM serving 🖥️

**Goal:** serve the model with flags chosen for this workload.

```bash
# edit scripts/start_vllm.sh to add your flags, then:
bash scripts/start_vllm.sh
# example starting point inside the script:
#   uv run python -m vllm.entrypoints.openai.api_server \
#     --model Qwen/Qwen3-30B-A3B-Instruct-2507 --host 0.0.0.0 --port 8000 \
#     --max-model-len 4096 --gpu-memory-utilization 0.90 --max-num-seqs 256

# in a SECOND VM shell (or tmux pane), confirm it loaded:
curl localhost:8000/v1/models
# fire a manual question (this is your screenshot):
curl -s localhost:8000/v1/chat/completions -H 'content-type: application/json' -d '{
  "model":"Qwen/Qwen3-30B-A3B-Instruct-2507",
  "messages":[{"role":"user","content":"Write SQLite SQL: how many rows in a table named circuits?"}]
}' | python3 -m json.tool
```

**Deliverables & logic:**
- `screenshots/vllm_manual_query.png` — proves the model serves and returns SQL. *Comes from:* screenshot the terminal showing vLLM running + the curl reply.
- `REPORT.md` §1 — your flags + one-line justifications. *Logic:* shows you tuned for the MoE / long-prompt / short-output shape, not defaults.

- [ ] vLLM serving at `:8000`, manual query returns SQL
- [ ] screenshot saved · REPORT §1 filled

---

## Phase 2 — Observability dashboard (💻 built / 🖥️ verify)

**Goal:** dashboard covering latency percentiles, throughput, KV cache.

The JSON is **done** (`infra/grafana/provisioning/dashboards/serving.json`, 11
panels). Grafana auto-loads it on `docker compose up`. To verify it reacts:
```bash
# 🖥️ generate some load so panels move, then screenshot Grafana:
uv run python load_test/driver.py --rps 5 --duration 60
```
Open `http://localhost:3000` (via tunnel) → dashboard "vLLM serving".

**Deliverables & logic:**
- `serving.json` (committed) — *done*. *Logic:* the panels answer "is it slow, and where in the request lifecycle?" (e2e vs TTFT vs decode vs queue) plus KV headroom.
- `screenshots/grafana_serving.png` — *Comes from:* screenshot the full dashboard while the load above runs.

- [x] dashboard JSON
- [ ] 🖥️ panels react under load · screenshot saved

---

## Phase 3 — Agent (💻 done / 🖥️ confirm)

**Goal:** verify→revise loop with an iteration cap. **Code is done.** Confirm on
the real model that a revise actually fires.
```bash
# 🖥️ start the agent (points at local vLLM by default):
uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001
# in another shell, ask something; look for >1 entry with "sql" in history:
curl -s localhost:8001/answer -H 'content-type: application/json' \
  -d '{"question":"List the names of all circuits in Italy.","db":"formula_1"}' | python3 -m json.tool
```
*(💻 To test on the Mac instead: set OpenAI keys in `.env`, then
`.venv-dev/bin/uvicorn agent.server:app --port 8001`.)*

**Deliverables & logic:**
- `agent/graph.py`, `agent/prompts.py` (committed) — *done*. *Logic:* `iterations > 1` or a `revise` node in `history` proves the loop does real work.

- [x] code done
- [ ] 🖥️ confirmed ≥1 question triggers a revise

---

## Phase 4 — Agent tracing (Langfuse) 🖥️

**Goal:** capture per-step traces; tag them for Phase 6.
1. Open `http://localhost:3001` → sign up (local, instant) → project is auto-created ("Default").
2. *Settings → API Keys* → create → copy **public** + **secret** keys.
3. Add to `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-...
   LANGFUSE_SECRET_KEY=sk-...
   LANGFUSE_HOST=http://localhost:3001
   ```
4. Restart the agent (it auto-enables the Langfuse hook when keys are present).
5. Fire ~10 questions **with tags** so they're filterable later:
   ```bash
   curl -s localhost:8001/answer -H 'content-type: application/json' \
     -d '{"question":"How many drivers are there?","db":"formula_1","tags":{"run":"baseline"}}'
   ```
6. In Langfuse, open a trace → see the `generate_sql / verify / (revise)` waterfall.

**Deliverables & logic:**
- `screenshots/langfuse_trace.png` — the waterfall of one request. *Logic:* this is your agent x-ray; in Phase 6 it tells you *which step* is slow.
- `screenshots/langfuse_tags.png` — the trace list showing your metadata tags.

- [ ] keys in `.env` · traces appear · both screenshots saved

---

## Phase 5 — Evals (💻 logic done / 🖥️ real numbers)

**Goal:** execution accuracy + per-iteration pass rate on the 30B endpoint.
```bash
# 🖥️ agent must be running; this hits ~60 vLLM calls (watch Grafana):
uv run python evals/run_eval.py --out results/eval_baseline.json
cat results/eval_baseline.json | python3 -m json.tool | head -20
```

**Deliverables & logic:**
- `results/eval_baseline.json` — *written by the runner itself.* Contains overall + `pass_rate_by_iteration`.
- `screenshots/grafana_eval_run.png` — screenshot Grafana during the run.
- `REPORT.md` §2 — *Logic:* compare `pass_rate_by_iteration[0]` (stop after generate) vs the last value. Equal → loop is decoration; higher → it earns its keep.

- [x] eval code
- [ ] 🖥️ baseline run · json + screenshot · REPORT §2

---

## Phase 6 — SLO diagnosis & iteration 🖥️ (25% — the main event)

**Goal:** P95 < 5s at 10+ RPS over 5 min; diagnose from metrics, fix, prove it.
```bash
uv run python load_test/driver.py --rps 10 --duration 300   # watch Grafana live
```
Loop: read which metric moves first (queue time? KV cache → 100%? TTFT?) → form
one hypothesis → change **one** vLLM flag → re-run → confirm that metric moved →
check if P95 followed. Re-eval after tuning:
```bash
uv run python evals/run_eval.py --out results/eval_after_tuning.json
```

**Deliverables & logic:**
- `screenshots/grafana_before.png` + `grafana_after.png` — the one change that moved the needle.
- `results/eval_after_tuning.json` — *Logic:* proves a speed fix didn't tank quality.
- `REPORT.md` §3 — the "saw X → hypothesized Y → changed Z → result W" log. *Logic:* diagnosis quality is graded above hitting the number.

- [ ] 🖥️ load test · before/after screenshots · after-tuning eval · REPORT §3

---

## Phase 7 — Report 💻

Finish `REPORT.md` (skeleton already in the repo): §1 config, §2 baseline eval,
§3 SLO cycle, §4 agent value (cite per-iteration pass rate), §5 specific
next steps. ≤ 3 pages, honest about misses.

- [ ] REPORT.md complete

---

## Master deliverables checklist

| Deliverable | Phase | Where it comes from | Status |
|---|---|---|---|
| `agent/graph.py`, `agent/prompts.py` | 3 | written | [x] |
| `evals/run_eval.py` | 5 | written | [x] |
| `infra/grafana/provisioning/dashboards/serving.json` | 2 | written | [x] |
| `results/eval_baseline.json` | 5 | eval runner output | [ ] 🖥️ |
| `results/eval_after_tuning.json` | 6 | eval runner output (`--out`) | [ ] 🖥️ |
| `screenshots/vllm_manual_query.png` | 1 | terminal screenshot | [ ] 🖥️ |
| `screenshots/grafana_serving.png` | 2 | Grafana under load | [ ] 🖥️ |
| `screenshots/langfuse_trace.png` | 4 | Langfuse UI | [ ] 🖥️ |
| `screenshots/langfuse_tags.png` | 4 | Langfuse UI | [ ] 🖥️ |
| `screenshots/grafana_eval_run.png` | 5 | Grafana during eval | [ ] 🖥️ |
| `screenshots/grafana_before.png` | 6 | Grafana | [ ] 🖥️ |
| `screenshots/grafana_after.png` | 6 | Grafana | [ ] 🖥️ |
| `REPORT.md` | 1,5,6,7 | write as you go | [ ] |

---

## Final submission

`.gitignore` excludes `results/*.json` and `screenshots/*.png` — **force-add** the
real deliverables:
```bash
git add -f results/*.json screenshots/*.png
git add REPORT.md GUIDE.md
git commit -m "Add GPU-phase deliverables: evals, screenshots, report"
git push
```
Then submit your repo URL: `https://github.com/codejacker/mlops-llm-inference-assignment`
(make it public first if required: `gh repo edit --visibility public`).

### Moving work between machines
```bash
# 💻 after editing on the Mac:
git add -A && git commit -m "..." && git push
# 🖥️ on the VM:
git pull
```
