FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN useradd --create-home --uid 1000 budget && mkdir -p /data/backups && chown -R budget /data
USER budget
ENV PATH="/app/.venv/bin:$PATH" \
    BUDGET_DATABASE_URL=sqlite:////data/budget.db \
    BUDGET_BACKUP_DIR=/data/backups \
    BUDGET_COOKIE_SECURE=true
VOLUME /data
EXPOSE 8000

# Backup, then migrate, then serve (Backend.md §10). One worker: the scheduler runs in-process.
CMD ["sh", "-c", "[ -f /data/budget.db ] && python -m app.cli backup || true; alembic upgrade head && python -m app.cli seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
