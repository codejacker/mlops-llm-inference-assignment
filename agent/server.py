"""FastAPI wrapper exposing the agent over HTTP.

Run:
    uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001

The /answer endpoint accepts {question, db, tags?} and returns the
agent's final SQL, the result rows, and per-iteration history.
"""
from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel

load_dotenv()

from agent.graph import AgentState, graph  # noqa: E402

# Langfuse callback handler. If keys are set we initialize it; failures
# are NOT swallowed - a misconfigured Langfuse should not silently
# produce zero traces.
_lf_handler: Any = None
if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
    from langfuse.langchain import CallbackHandler

    _lf_handler = CallbackHandler()


app = FastAPI()

# --- Agent-layer Prometheus metrics ---------------------------------------
# The SLO is end-to-end /answer latency (the full generate->execute->verify->
# revise chain). vLLM's own /metrics can only see a single LLM call, so without
# this the bottleneck is invisible in Grafana. Buckets span sub-second to
# minutes because an overloaded chain can take >60s.
AGENT_LATENCY = Histogram(
    "agent_request_duration_seconds",
    "End-to-end /answer latency: full generate->execute->verify->revise chain.",
    buckets=(0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 300),
)
AGENT_REQUESTS = Counter(
    "agent_requests_total",
    "Agent /answer requests by outcome.",
    ["outcome"],  # ok | sql_error | exception
)
AGENT_ITERATIONS = Histogram(
    "agent_iterations",
    "generate/revise iterations performed per request.",
    buckets=(1, 2, 3, 4, 5),
)

# Exposes the metrics above at GET /metrics on the agent port (8001).
app.mount("/metrics", make_asgi_app())


class AnswerRequest(BaseModel):
    question: str
    db: str
    tags: dict[str, str] = {}


class AnswerResponse(BaseModel):
    sql: str
    rows: list[list[Any]] | None
    iterations: int
    ok: bool
    error: str | None = None
    history: list[dict[str, Any]] = []


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/answer", response_model=AnswerResponse)
def answer(req: AnswerRequest) -> AnswerResponse:
    start = time.perf_counter()
    outcome = "exception"
    try:
        resp = _run_answer(req)
        outcome = "ok" if resp.ok else "sql_error"
        AGENT_ITERATIONS.observe(resp.iterations)
        return resp
    finally:
        AGENT_LATENCY.observe(time.perf_counter() - start)
        AGENT_REQUESTS.labels(outcome=outcome).inc()


def _run_answer(req: AnswerRequest) -> AnswerResponse:
    state = AgentState(question=req.question, db_id=req.db)
    config: dict[str, Any] = {
        "callbacks": [_lf_handler] if _lf_handler is not None else [],
        "metadata": req.tags,
    }
    try:
        final = graph.invoke(state, config=config)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    sql = final.get("sql", "")
    iteration = final.get("iteration", 0)
    history = final.get("history", [])
    execution = final.get("execution")

    if execution is None:
        return AnswerResponse(
            sql=sql,
            rows=None,
            iterations=iteration,
            ok=False,
            error="agent produced no execution result",
            history=history,
        )
    if not execution.ok:
        return AnswerResponse(
            sql=sql,
            rows=None,
            iterations=iteration,
            ok=False,
            error=execution.error,
            history=history,
        )

    return AnswerResponse(
        sql=sql,
        rows=[list(r) for r in (execution.rows or [])],
        iterations=iteration,
        ok=True,
        history=history,
    )
