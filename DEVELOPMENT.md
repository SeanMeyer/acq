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
| `team-ui` | Review dashboard | TypeScript, React, Vite |

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
