# Per-User Agent Keys via GitHub Device Flow

## Problem

Agent API keys are currently a static JSON env var (`ACQ_API_KEYS`) on the team API server. To onboard a new user, someone must manually add their key to that env var and redeploy. Users also need to be told the key out-of-band (Slack, etc.), and all contributions are tied to whatever agent name the static mapping defines — there's no connection to the user's actual identity.

## Solution

Users run `make setup` which triggers GitHub's device flow, authenticates them, generates a per-user agent API key stored in the database, and writes it to their `~/.claude/settings.json`. No manual key distribution, no server redeployment.

## User Flow

```
$ make setup
...dependency install...

To authenticate with acq, open this URL in your browser:
  https://github.com/login/device

And enter this code: ABCD-1234

Waiting for authorization...

Authenticated as seanmeyer (Sean Meyer)

Agent key written to ~/.claude/settings.json:
  ACQ_TEAM_API_KEY = acq_abc123...
  ACQ_AGENT_NAME   = seanmeyer-agent
  ACQ_TEAM_ADDR    = https://acq.example.com

You're ready to use acq.
```

## Server-Side Changes

### New table: `agent_keys`

```sql
CREATE TABLE IF NOT EXISTS agent_keys (
    id SERIAL PRIMARY KEY,
    api_key TEXT NOT NULL UNIQUE,
    agent_name TEXT NOT NULL UNIQUE,
    github_username TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

One key per GitHub user. If a user runs setup again, they get their existing key back.

### New endpoint: `POST /auth/agent-key`

- Accepts: `Authorization: Bearer <github-access-token>` header
- Validates the token against GitHub's API (`GET https://api.github.com/user`)
- If the user already has a key in `agent_keys`, returns it
- Otherwise generates a new key (`acq_` + random hex), stores it, returns it
- Returns: `{"api_key": "acq_...", "agent_name": "{github_username}-agent", "github_username": "..."}`

### Changes to `get_agent_identity`

Currently reads from the `ACQ_API_KEYS` env var only. After this change:

1. Check the `agent_keys` table for the provided `X-API-Key`
2. If not found and `ACQ_API_KEYS` env var is set, check the static mapping (for dev/test)
3. If neither matches, return 401

Production deploys don't set `ACQ_API_KEYS` — all auth goes through the database. Tests continue to monkeypatch the env var.

## Client-Side Script

`scripts/setup-agent.py` — runs as part of `make setup`.

### GitHub Device Flow steps:

1. `POST https://github.com/login/device/code` with `client_id` and `scope=read:user`
2. Print the `verification_uri` and `user_code` to the terminal
3. Poll `POST https://github.com/login/oauth/access_token` with `device_code`, `client_id`, `grant_type=urn:ietf:params:oauth:grant-type:device_code` at the `interval` specified in step 1
4. On success, get back a GitHub access token
5. `POST {ACQ_TEAM_ADDR}/auth/agent-key` with `Authorization: Bearer <github-token>`
6. Get back `api_key`, `agent_name`
7. Write to `~/.claude/settings.json`, merging into existing `env` block

### Settings.json merge:

Read existing file, parse JSON, set `env.ACQ_TEAM_API_KEY`, `env.ACQ_AGENT_NAME`, `env.ACQ_TEAM_ADDR`, write back. Preserve all other settings.

### Configuration:

The team API URL and GitHub OAuth client ID are hardcoded in the script (or read from a config file in the repo). The client secret is NOT needed for device flow — only the client_id.

## Identity Model

After this change, a user like Sean has two identities in acq:

| Identity | `created_by` | `created_by_type` | Source |
|----------|-------------|-------------------|--------|
| Agent | `seanmeyer-agent` | `agent` | MCP server via API key |
| Human | `seanmeyer` | `human` | Review UI via GitHub OAuth |

Same person, distinguishable by suffix and type. Human votes still count 5x in ranking.

## Makefile Changes

`make setup` currently only installs dependencies. After this change:

```makefile
.PHONY: setup
setup:
	(cd shared && uv sync --group dev)
	(cd plugins/acq/server && uv sync --group dev)
	(cd team-api && uv sync --group dev)
	(cd team-ui && pnpm install $(if $(CI),--frozen-lockfile,))
	@echo ""
	@echo "Setting up agent authentication..."
	python scripts/setup-agent.py
```

## What's NOT Changing

- Review UI GitHub OAuth (redirect-based) — untouched
- Local-only mode — still works without any auth
- `ACQ_API_KEYS` env var — kept for dev/test, not used in production
- MCP server code — still reads `ACQ_TEAM_API_KEY` and `ACQ_AGENT_NAME` from env
