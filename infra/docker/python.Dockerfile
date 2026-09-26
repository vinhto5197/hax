# syntax=docker/dockerfile:1.7
# One image for api, worker and the migrate one-shot: identical code and
# dependencies, different commands (compose sets them).
FROM python:3.14-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# A compiler for any dependency that has no wheel for this interpreter; it
# stays in this stage and never reaches the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
# Runtime dependencies only — the project itself is deliberately NOT installed,
# so site-packages never holds a second, build-time snapshot of packages/ that
# could shadow the COPYed tree. /app is the only copy of the code in the image.
RUN python -c "import pathlib,tomllib;pathlib.Path('requirements.txt').write_text(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))"
RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install -r requirements.txt

FROM python:3.14-slim AS runtime
# PYTHONPATH pins /app as the import root. Without it each entrypoint reaches
# the code by its own cwd heuristic (uvicorn's --app-dir, celery's temporary
# cwd_in_path, alembic's prepend_sys_path), which all break the moment a
# command runs from anywhere but /app.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH" \
    PYTHONPATH=/app
WORKDIR /app
RUN useradd --system --uid 10001 --create-home hax
COPY --from=builder /venv /venv
# Per-service, not `COPY apps`: `apps/web` belongs to the Next image only, and
# copying it here would rebuild this image on every web-only change.
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY packages ./packages
COPY alembic.ini ./alembic.ini
USER hax
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
