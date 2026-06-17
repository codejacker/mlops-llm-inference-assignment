# Optional container for the AGENT server (Phase 3 service), not vLLM.
#
# The assignment does NOT require this - on the VM you can just run
#   uv run uvicorn agent.server:app --port 8001
# This image exists so the agent can ship as a self-contained unit and so you
# can see how a Dockerfile is structured. It deliberately installs ONLY the
# agent deps (requirements-dev.txt), never vllm - vllm runs on the host GPU.
#
# How to read a Dockerfile: each line is a build step that produces a cached
# layer. Order matters - put rarely-changing steps (deps) BEFORE often-changing
# steps (your code) so editing code doesn't reinstall every package.

# 1. Base image: a small official Python. "slim" = Debian minus the extras.
FROM python:3.12-slim

# 2. Where commands run and code lives inside the container.
WORKDIR /app

# 3. Copy ONLY the dependency manifest first, then install. Because this layer
#    is cached on the file's contents, editing agent code later does NOT trigger
#    a reinstall - only changing requirements-dev.txt does.
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# 4. Now copy the application code (changes often -> later layer).
COPY agent/ ./agent/

# 5. Document the port the server listens on. (Publishing is done at run time
#    with -p; EXPOSE is just metadata/intent.)
EXPOSE 8001

# 6. Default config. Override at run time with -e. host.docker.internal lets the
#    container reach a vLLM running on the host machine.
ENV VLLM_BASE_URL=http://host.docker.internal:8000/v1 \
    VLLM_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507

# 7. The process the container runs. 0.0.0.0 = listen on all interfaces so the
#    published port is reachable from outside the container.
CMD ["uvicorn", "agent.server:app", "--host", "0.0.0.0", "--port", "8001"]

# Build:  docker build -t sql-agent .
# Run:    docker run --rm -p 8001:8001 \
#           --add-host host.docker.internal:host-gateway \
#           -v "$(pwd)/data:/app/data:ro" \          # agent needs the sqlite DBs
#           --env-file .env \                         # Langfuse keys, base url
#           sql-agent
