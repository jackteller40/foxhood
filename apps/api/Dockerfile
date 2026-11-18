# Foxhood API. Built by Cloud Build (no Docker needed on your laptop); runs on Cloud Run.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

# Run as an unprivileged user.
RUN useradd --uid 10001 --no-create-home foxhood
USER foxhood

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080 \
    ENVIRONMENT=production \
    LANGSMITH_TRACING=false

# Cloud Run sets $PORT. Proxy headers so request URLs and client IPs are right behind Google's front end.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
