# Backend image (FastAPI API + arq worker share this image).
#
# Design notes (05_stage00/20261111_b00_design.md):
#  - D6: dependencies live in /opt/venv, NOT /app, because docker-compose
#        bind-mounts ./backend over /app in dev and would hide an in-tree venv.
#  - D7: runs as UID 1000 so files written to bind mounts (logs/audit, caches)
#        are owned by the host developer account.
FROM python:3.12-slim

# uv: fast, lockfile-based installer (dev_tools.md). Pinned for reproducible builds.
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid ${APP_GID} app \
 && useradd --uid ${APP_UID} --gid ${APP_GID} --create-home app \
 && mkdir -p /opt/venv /app /var/log/app/audit \
 && chown -R app:app /opt/venv /app /var/log/app

USER app
WORKDIR /app

# Install dependencies first (cached layer) — only re-runs when they change.
# --frozen when a lockfile exists keeps builds reproducible; the first build
# (no uv.lock yet) resolves fresh.
COPY --chown=app:app pyproject.toml uv.lock* ./
RUN if [ -f uv.lock ]; then uv sync --frozen --no-install-project; \
    else uv sync --no-install-project; fi

# Application code (in dev this is shadowed by the bind mount, which is fine).
COPY --chown=app:app . .

EXPOSE 8200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
