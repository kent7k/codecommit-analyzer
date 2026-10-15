# arm64（Graviton）前提。build: docker build --platform linux/arm64 .
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project

COPY analyzer ./analyzer
RUN uv sync --no-dev --no-editable 2>/dev/null || true

# root で git clone させない
RUN useradd --create-home --uid 10001 worker \
 && mkdir -p /work && chown worker:worker /work
USER worker
ENV PATH="/app/.venv/bin:${PATH}" \
    WORK_DIR=/work

ENTRYPOINT ["python", "-m", "analyzer.main"]
