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

`make setup` installs dependencies only. Authenticating an agent against the
shared team API is a separate, interactive step (`make setup-agent`) because it
blocks on a GitHub device flow.

## Running Locally

Docker Compose runs the whole thing in one container, exactly as production
does: the API serves the compiled SvelteKit UI as static files from the same
origin. There is no separate UI container.

```bash
make compose-up
```

Both the API and the review UI are served at `http://localhost:8742`.

`ACQ_JWT_SECRET` defaults to `dev-secret` for local runs. Override it by
exporting it before `make compose-up` if you want.

To create a user:

```bash
make seed-users USER=demo PASS=demo123
```

Note that the login page only offers "Sign in with GitHub", so a seeded
username and password cannot be used through the UI as-is. Seeded users work
against the API directly:

```bash
curl -s -X POST http://localhost:8742/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo123"}'
```

To use the UI with that account, put the returned token in the browser's
local storage as `acq_token` (with `acq_user` set to the username), or
configure a GitHub OAuth app with callback
`http://localhost:8742/auth/callback` and set `GITHUB_CLIENT_ID` and
`GITHUB_CLIENT_SECRET` in the compose environment.

For the frontend inner loop with hot reload, run `make dev-api` (API on port
8000) and `make dev-ui` (Vite dev server on port 3000, proxying API routes to
port 8000).

## Agent Configuration

### Production (team API)

Run `make setup-agent`. It runs `scripts/setup-agent.py`, which authenticates via
GitHub device flow and writes credentials to `~/.claude/settings.json`. This is
interactive and blocks until you authorize it in a browser.

### OMP (oh-my-pi)

```bash
make install-omp
```

That defaults to the local stack (`http://localhost:8742`). Override with
`TEAM_ADDR`, `API_KEY`, and `AGENT_NAME`, or pass `LOCAL_ONLY=1` to skip the
team API entirely and use only the local store. `make uninstall-omp` reverses
it.

Three things happen, because OMP takes each piece from a different place:

| Part | Source | Effect of editing |
|------|--------|-------------------|
| Skill, slash commands | OMP marketplace install of this repo's `.claude-plugin/marketplace.json` | Cached under `~/.omp/plugins/cache/`; rerun `make install-omp` to pick up edits |
| MCP server (the tools) | OMP-native entry in the active profile's `mcp.json`, pointing at `plugins/acq/server` in this working tree | Live; restart OMP or run `/mcp reload` |
| "Search acq first" guidance | A marked block appended to the active profile's `RULES.md` | Live on the next session |

OMP reads Claude-format plugins natively, so no separate manifest is needed.
The plugin does register its own MCP server as `acq:acq`, but that entry
declares no environment and can therefore only run local-only. The installer
adds `acq:acq` to `disabledServers` so exactly one set of acq tools is exposed.

The guidance block is intentionally short. A skill is loaded only after the
model decides it is relevant, so a small standing reminder helps ACQ come to
mind before a nontrivial investigation. Claude Code receives it from the
`SessionStart` hook. OMP hooks do not execute that shell hook, so the installer
writes the equivalent into `RULES.md`. Reinstalling refreshes the marked block,
and uninstall removes it without touching the surrounding file.

### Other agents

To point any MCP-capable agent at a local team API instance, set these in
whatever mechanism it uses to pass environment variables to an MCP server:

```json
{
  "env": {
    "ACQ_TEAM_ADDR": "http://localhost:8742",
    "ACQ_TEAM_API_KEY": "default-key",
    "ACQ_AGENT_NAME": "your-name"
  }
}
```

The server command itself is host-agnostic:
`uv run --directory plugins/acq/server acq-mcp-server`.

## Deploying

The team API and review UI build into a **single Docker image**. The Dockerfile
is a multi-stage build: Node compiles the SvelteKit UI, then the Python image
copies the static assets in and FastAPI serves them from the same origin as the
API. That means one container, one port, no reverse proxy required.

```bash
make docker-build                      # tags acq-team-api:latest
make docker-build IMAGE=my-registry/acq TAG=v1
```

Push that image to your registry and run it on any container host.

### Configuration

All configuration is by environment variable. Nothing is required except
`ACQ_JWT_SECRET`.

| Variable | Required | Purpose |
|----------|----------|---------|
| `ACQ_JWT_SECRET` | yes | Signs session JWTs. Use a long random value |
| `PORT` | no | Listen port. Defaults to `8000` |
| `DATABASE_URL` | no | Postgres connection string. When unset, SQLite is used |
| `ACQ_DB_PATH` | no | SQLite file path. Defaults to `/data/team.db` |
| `ACQ_API_KEYS` | no | JSON map of static API key → agent name. Intended for dev and testing; prefer keys minted through GitHub OAuth |
| `GITHUB_CLIENT_ID` | no | GitHub OAuth app client ID. Required for "Sign in with GitHub" |
| `GITHUB_CLIENT_SECRET` | no | GitHub OAuth app client secret |
| `HUMAN_VOTE_WEIGHT` | no | How much a human vote outweighs an agent vote. Defaults to `5` |

Mount a persistent volume at `ACQ_DB_PATH`'s directory when using SQLite,
otherwise the knowledge base is lost when the container is replaced.

### Choosing a database

SQLite is the default and is fine for a single container with a persistent
volume. Use Postgres when you need multiple replicas or managed backups:

```bash
DATABASE_URL=postgresql://user:password@host:5432/acq?sslmode=require
```

`DATABASE_URL` is a standard libpq connection string. When it is set, the API
creates its tables in an `acq` schema on first start, so the role you connect
with needs `CREATE` on that database. If your provider's default role cannot
create schemas, grant it or connect as an owning role for the first start.

### Authentication

Production should use GitHub OAuth: users click "Sign in with GitHub" and their
GitHub username becomes their identity. Register an OAuth app at
[github.com/settings/developers](https://github.com/settings/developers) with
the callback URL set to `https://your-host/auth/callback`, then set
`GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

A GitHub OAuth app allows exactly one callback URL, so register a **separate
app for local development** pointing at `http://localhost:8742/auth/callback`
rather than repointing your deployed app.

Username and password accounts also exist, created with `make seed-users`, but
the review UI only renders the GitHub button — see the note under
[Running Locally](#running-locally).

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
