# --- Stage 1: Build UI ---
FROM node:22-slim AS ui-build
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /app
COPY team-ui/package.json team-ui/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY team-ui/ .
ENV VITE_API_BASE=""
RUN pnpm build

# --- Stage 2: Build API ---
FROM python:3.12.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends daemontools libpq-dev && rm -rf /var/lib/apt/lists/*

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

EXPOSE 8000

CMD ["envdir", "/etc/datadog/secrets", "/app/team-api/.venv/bin/acq-team-api"]
