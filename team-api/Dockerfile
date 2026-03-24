FROM python:3.12.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.22 /uv /uvx /bin/

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

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /data && chown app:app /data
USER app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8742

CMD ["/app/team-api/.venv/bin/acq-team-api"]
