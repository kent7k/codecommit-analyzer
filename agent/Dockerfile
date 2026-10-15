# AgentCore Runtime は linux/arm64 のコンテナを要求する。
# build: docker build --platform linux/arm64 .
FROM --platform=linux/arm64 python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen --no-install-project 2>/dev/null || uv sync --no-dev --no-install-project
COPY app.py memory.py tools.py ./

# AgentCore Observability: ADOT で自動計装し、ランタイムが用意する OTLP へ流す
RUN uv pip install --python /app/.venv/bin/python aws-opentelemetry-distro

RUN useradd --create-home --uid 10001 agent
USER agent
ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8080

CMD ["opentelemetry-instrument", "python", "app.py"]
