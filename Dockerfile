# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

COPY pyproject.toml uv.lock README.md .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY packages/backend/src ./packages/backend/src
COPY packages/backend/alembic.ini ./packages/backend/alembic.ini
# BACKEND_ROOT resolves Alembic files relative to the editable source tree.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.12-slim-bookworm

WORKDIR /app
ENV APP_ENV=prod \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages/backend /app/packages/backend

USER app
EXPOSE 8000
CMD ["api"]
