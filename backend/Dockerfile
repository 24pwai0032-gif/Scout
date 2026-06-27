# Scout v1 — one image runs the FastAPI backend + agent + MCP server + capture pipeline.
# (The MCP server is launched as a stdio subprocess by the agent; same container is fine
#  for v1. Split it / the queue worker out when you scale — see README "Why one container".)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml ./
COPY scout ./scout
RUN pip install --upgrade pip && pip install ".[agent,api,notify,postgres]"

# App code (eval, scripts, migrations) for completeness.
COPY eval ./eval
COPY scripts ./scripts
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Default: the backend API (webhook receiver + on-demand runs + findings).
CMD ["uvicorn", "scout.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
