# Development

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [pnpm](https://pnpm.io/)
- Docker and Docker Compose

## Repository Structure

| Directory | Component | Stack |
|-----------|-----------|-------|
| `shared` | Shared models, scoring, schema | Python, Pydantic |
| `plugins/acq/server` | MCP server (plugin) | Python, FastMCP |
| `team-api` | Team Q&A API | Python, FastAPI |
| `team-ui` | Review dashboard | TypeScript, SvelteKit, Tailwind |

## Initial Setup

```bash
git clone https://github.com/seanmeyer/acq.git
cd acq
make setup
```

## Running Locally

The quickest way to run everything is with Docker Compose.

Export the required secret first:

```bash
export ACQ_JWT_SECRET=dev-secret
```

Start all services (runs in the foreground):

```bash
make compose-up
```

In a separate terminal, create a user:

```bash
make seed-users USER=demo PASS=demo123
```

The team API is available at `http://localhost:8742`.
The review UI is available at `http://localhost:3000`.

For isolated component testing outside Docker, use `make dev-api` (team API) and `make dev-ui` (dashboard).

## Agent Configuration

To point your agent at a local team API instance, set `ACQ_TEAM_ADDR` and `ACQ_TEAM_API_KEY`.

### Claude Code

Add to `~/.claude/settings.json` under the `env` key:

```json
{
  "env": {
    "ACQ_TEAM_ADDR": "http://localhost:8742",
    "ACQ_TEAM_API_KEY": "default-key"
  }
}
```

## Deploying to Howler

The team API and review UI are bundled into a single Docker image and deployed to [Howler](https://howler.us1.staging.dog/) (service ID 222). The Dockerfile uses a multi-stage build: Node builds the SvelteKit UI, then the Python image copies in the static assets and serves them via FastAPI.

### Secrets

These are configured via the Howler UI or API at `/api/services/222/secrets/`:

| Secret | Purpose |
|--------|---------|
| `ACQ_JWT_SECRET` | Signs session JWTs |
| `ACQ_API_KEYS` | JSON map of API key → agent name for MCP clients |
| `ORGSTORE_CLUSTER` | DogPark cluster name (enables Postgres) |
| `DB_NAME` | DogPark database name |
| `DB_USER` | DogPark database role |
| `DB_HOST` | pg-proxy host (auto-derived if not set) |
| `GITHUB_CLIENT_ID` | GitHub OAuth app client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth app client secret |

### Deploy

Build a tarball with the Dockerfile at root and deploy:

```bash
tmpdir=$(mktemp -d)
cp team-api/Dockerfile "$tmpdir/Dockerfile"
cp -r shared team-api team-ui "$tmpdir/"
tar czf /tmp/acq-deploy.tar.gz -C "$tmpdir" .
curl -X POST "https://howler.us1.staging.dog/api/services/222/builds/" \
  -F "build-context.tgz=@/tmp/acq-deploy.tar.gz"
```

The response streams build and deploy logs. The field name **must** be `build-context.tgz` — any other name returns a silent 500.

The service is live at `https://acq-team-api.us1.staging.dog/` once the deploy finishes. Fabric destinations and routing domains are already configured.

### Authentication

Production uses GitHub OAuth — users click "Sign in with GitHub" and their GitHub username becomes their identity. The GitHub OAuth app is registered at [github.com/settings/applications](https://github.com/settings/applications) with callback URL `https://acq-team-api.us1.staging.dog/auth/callback`.

Local dev (docker-compose) still uses username/password via `make seed-users`.

## Docker Compose

| Command | Purpose |
|---------|---------|
| `make compose-up` | Build and start services |
| `make compose-down` | Stop services |
| `make compose-reset` | Stop services and wipe database |
| `make seed-users USER=demo PASS=demo123` | Create a user |

## Validation

| Command | Purpose |
|---------|---------|
| `make lint` | Format and lint all Python components |
| `make test` | Run tests across shared, team-api, and MCP server |
