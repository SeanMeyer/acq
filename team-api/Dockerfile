# --- Stage 1: Build UI ---
FROM node:22-slim AS ui-build
# CI=true keeps pnpm non-interactive; it otherwise aborts when it wants to
# confirm removing a modules directory and finds no TTY.
ENV CI=true
RUN corepack enable
WORKDIR /app
COPY team-ui/package.json team-ui/pnpm-lock.yaml team-ui/pnpm-workspace.yaml ./
# Resolve pnpm from package.json's "packageManager" field so the Docker build,
# CI, and local installs all use one pinned version. An unpinned "pnpm@latest"
# is what previously broke this build when pnpm 11 changed its behaviour.
RUN corepack install
RUN pnpm install --frozen-lockfile
COPY team-ui/ .
ENV VITE_API_BASE=""
RUN pnpm build

# --- Stage 2: Build API ---
FROM python:3.12.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the shared package first
COPY shared/pyproject.toml shared/pyproject.toml
COPY shared/acq_shared/ shared/acq_shared/
RUN cd shared && uv sync --no-dev

# Install team-api dependencies (cached independently of app code)
COPY team-api/pyproject.toml team-api/uv.lock team-api/
RUN cd team-api && uv sync --no-dev --frozen --no-install-project

# Copy application code and install
COPY team-api/team_api/ team-api/team_api/
RUN cd team-api && uv sync --no-dev --frozen

# Copy built UI assets
COPY --from=ui-build /app/build /app/static

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /data && chown app:app /data
USER app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The app honours PORT and defaults to 8000.
EXPOSE 8000

CMD ["/app/team-api/.venv/bin/acq-team-api"]
