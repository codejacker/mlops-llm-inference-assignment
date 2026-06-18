#!/usr/bin/env bash
set -euo pipefail

MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507"

exec uv run --no-sync python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.92 \
    --max-num-seqs 64 \
    --quantization fp8
