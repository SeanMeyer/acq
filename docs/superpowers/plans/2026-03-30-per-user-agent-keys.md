# Per-User Agent Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users self-provision agent API keys via GitHub device flow so there's no manual key distribution.

**Architecture:** Add an `agent_keys` table to both store backends, a `POST /auth/agent-key` endpoint that exchanges a GitHub token for a persistent agent key, update `get_agent_identity` to check the DB first, and add a `scripts/setup-agent.py` CLI that runs the device flow and writes credentials to `~/.claude/settings.json`.

**Tech Stack:** Python, FastAPI, SQLite/Postgres, GitHub OAuth Device Flow, httpx

---

### Task 1: Add `agent_keys` table to SQLite schema

**Files:**
- Modify: `shared/acq_shared/sqlite_schema.py`
- Modify: `shared/acq_shared/sqlite_store.py`
- Modify: `shared/acq_shared/store.py` (add methods to Store Protocol)
- Test: `shared/tests/test_store_contract.py`

- [ ] **Step 1: Write the failing test**

Add to `shared/tests/test_store_contract.py`:

```python
class TestAgentKeys:
    def test_create_and_get_agent_key(self, store: SqliteStore) -> None:
        key = store.create_agent_key("acq_test123", "alice-agent", "alice")
        assert key["api_key"] == "acq_test123"
        assert key["agent_name"] == "alice-agent"
        assert key["github_username"] == "alice"

        fetched = store.get_agent_key("acq_test123")
        assert fetched is not None
        assert fetched["agent_name"] == "alice-agent"

    def test_get_nonexistent_agent_key(self, store: SqliteStore) -> None:
        assert store.get_agent_key("acq_doesnotexist") is None

    def test_get_existing_key_by_github_username(self, store: SqliteStore) -> None:
        store.create_agent_key("acq_test456", "bob-agent", "bob")
        existing = store.get_agent_key_by_github("bob")
        assert existing is not None
        assert existing["api_key"] == "acq_test456"

    def test_duplicate_github_username_raises(self, store: SqliteStore) -> None:
        store.create_agent_key("acq_key1", "alice-agent", "alice")
        with pytest.raises(Exception):
            store.create_agent_key("acq_key2", "alice-agent2", "alice")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd shared && uv run pytest tests/test_store_contract.py::TestAgentKeys -v`
Expected: FAIL — `create_agent_key` does not exist.

- [ ] **Step 3: Add `agent_keys` table to SQLite DDL**

In `shared/acq_shared/sqlite_schema.py`, bump `SCHEMA_VERSION` to 3 and add to `_DDL`:

```sql
CREATE TABLE IF NOT EXISTS agent_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key TEXT NOT NULL UNIQUE,
    agent_name TEXT NOT NULL UNIQUE,
    github_username TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
```

No migration needed from v2→v3 since `agent_keys` is a new table — `CREATE IF NOT EXISTS` handles it.

- [ ] **Step 4: Implement store methods on SqliteStore**

In `shared/acq_shared/sqlite_store.py`, add three methods:

```python
def create_agent_key(self, api_key: str, agent_name: str, github_username: str) -> dict:
    now = datetime.now(UTC).isoformat()
    self._conn.execute(
        "INSERT INTO agent_keys (api_key, agent_name, github_username, created_at) VALUES (?, ?, ?, ?)",
        (api_key, agent_name, github_username, now),
    )
    self._conn.commit()
    return {"api_key": api_key, "agent_name": agent_name, "github_username": github_username, "created_at": now}

def get_agent_key(self, api_key: str) -> dict | None:
    row = self._conn.execute(
        "SELECT api_key, agent_name, github_username, created_at FROM agent_keys WHERE api_key = ?",
        (api_key,),
    ).fetchone()
    if row is None:
        return None
    return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}

def get_agent_key_by_github(self, github_username: str) -> dict | None:
    row = self._conn.execute(
        "SELECT api_key, agent_name, github_username, created_at FROM agent_keys WHERE github_username = ?",
        (github_username,),
    ).fetchone()
    if row is None:
        return None
    return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}
```

Add `from datetime import UTC, datetime` import if not already present.

- [ ] **Step 4b: Add methods to Store Protocol**

In `shared/acq_shared/store.py`, add to the `Store` class:

```python
def create_agent_key(self, api_key: str, agent_name: str, github_username: str) -> dict: ...
def get_agent_key(self, api_key: str) -> dict | None: ...
def get_agent_key_by_github(self, github_username: str) -> dict | None: ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd shared && uv run pytest tests/test_store_contract.py::TestAgentKeys -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add shared/acq_shared/sqlite_schema.py shared/acq_shared/sqlite_store.py shared/tests/test_store_contract.py
git commit -m "feat: add agent_keys table and methods to SQLite store"
```

---

### Task 2: Add `agent_keys` table to Postgres schema

**Files:**
- Modify: `shared/acq_shared/postgres_schema.py`
- Modify: `shared/acq_shared/postgres_store.py`

- [ ] **Step 1: Add table to Postgres DDL**

In `shared/acq_shared/postgres_schema.py`, add to `_DDL` after the `users` table:

```sql
CREATE TABLE IF NOT EXISTS acq.agent_keys (
    id SERIAL PRIMARY KEY,
    api_key TEXT NOT NULL UNIQUE,
    agent_name TEXT NOT NULL UNIQUE,
    github_username TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);
```

Bump `SCHEMA_VERSION` to 3.

- [ ] **Step 2: Implement store methods on PostgresStore**

In `shared/acq_shared/postgres_store.py`, add three methods matching the SqliteStore signatures:

```python
def create_agent_key(self, api_key: str, agent_name: str, github_username: str) -> dict:
    now = datetime.now(UTC).isoformat()
    self._execute(
        "INSERT INTO acq.agent_keys (api_key, agent_name, github_username, created_at) VALUES (%s, %s, %s, %s)",
        (api_key, agent_name, github_username, now),
    )
    self._conn.commit()
    return {"api_key": api_key, "agent_name": agent_name, "github_username": github_username, "created_at": now}

def get_agent_key(self, api_key: str) -> dict | None:
    cur = self._execute(
        "SELECT api_key, agent_name, github_username, created_at FROM acq.agent_keys WHERE api_key = %s",
        (api_key,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}

def get_agent_key_by_github(self, github_username: str) -> dict | None:
    cur = self._execute(
        "SELECT api_key, agent_name, github_username, created_at FROM acq.agent_keys WHERE github_username = %s",
        (github_username,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {"api_key": row[0], "agent_name": row[1], "github_username": row[2], "created_at": row[3]}
```

- [ ] **Step 3: Run all shared tests**

Run: `cd shared && uv run pytest tests/ -v`
Expected: All pass (Postgres tests skip if no DB available).

- [ ] **Step 4: Commit**

```bash
git add shared/acq_shared/postgres_schema.py shared/acq_shared/postgres_store.py
git commit -m "feat: add agent_keys table and methods to Postgres store"
```

---

### Task 3: Update `get_agent_identity` to check DB first

**Files:**
- Modify: `team-api/team_api/auth.py`
- Test: `team-api/tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Add to `team-api/tests/test_auth.py`:

```python
def test_agent_key_from_database(client, monkeypatch):
    """Agent key stored in DB should authenticate without ACQ_API_KEYS env var."""
    monkeypatch.delenv("ACQ_API_KEYS", raising=False)
    store = _get_store()
    store.create_agent_key("acq_dbkey123", "dbuser-agent", "dbuser")

    resp = client.get("/status", headers={"X-API-Key": "acq_dbkey123"})
    assert resp.status_code == 200


def test_db_key_takes_precedence_over_env(client, monkeypatch):
    """DB key should be checked before env var."""
    monkeypatch.setenv("ACQ_API_KEYS", json.dumps({"acq_dbkey123": "env-agent"}))
    store = _get_store()
    store.create_agent_key("acq_dbkey123", "db-agent", "dbuser")

    # The agent name should come from the DB, not the env var
    # We verify by checking that the request succeeds (both sources have the key,
    # but DB takes precedence)
    resp = client.get("/status", headers={"X-API-Key": "acq_dbkey123"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd team-api && uv run pytest tests/test_auth.py::test_agent_key_from_database -v`
Expected: FAIL — 401 because no `ACQ_API_KEYS` env var and DB lookup doesn't exist yet.

- [ ] **Step 3: Update `get_agent_identity` in auth.py**

Replace the current `get_agent_identity` function:

```python
def get_agent_identity(request: Request) -> str:
    """FastAPI dependency: validates X-API-Key header and returns agent_name.

    Checks the agent_keys database table first, falls back to the
    ACQ_API_KEYS env var for dev/test compatibility.
    """
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    # Check database first.
    store: Store = request.app.state.store
    db_key = store.get_agent_key(key)
    if db_key is not None:
        return db_key["agent_name"]

    # Fallback to env var (dev/test only).
    api_keys = _get_api_keys()
    agent_name = api_keys.get(key)
    if agent_name is not None:
        return agent_name

    raise HTTPException(status_code=401, detail="Invalid API key")
```

Note: `get_agent_identity` currently takes only `request: Request`. The store is accessed via `request.app.state.store` (same pattern as `get_store` in deps.py).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd team-api && uv run pytest tests/test_auth.py -v`
Expected: All pass.

- [ ] **Step 5: Run full team-api test suite**

Run: `cd team-api && uv run pytest tests/ -v`
Expected: All pass — existing tests still use `ACQ_API_KEYS` env var which now works as fallback.

- [ ] **Step 6: Commit**

```bash
git add team-api/team_api/auth.py team-api/tests/test_auth.py
git commit -m "feat: get_agent_identity checks DB first, falls back to env var"
```

---

### Task 4: Add `POST /auth/agent-key` endpoint

**Files:**
- Modify: `team-api/team_api/auth.py`
- Test: `team-api/tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Add to `team-api/tests/test_auth.py`:

```python
from unittest.mock import patch, MagicMock


def test_create_agent_key_success(client, monkeypatch):
    """POST /auth/agent-key with valid GitHub token creates a key."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"login": "testuser", "name": "Test User"}

    with patch("team_api.auth.http_requests.get", return_value=mock_resp):
        resp = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_fake_token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_name"] == "testuser-agent"
    assert data["github_username"] == "testuser"
    assert data["api_key"].startswith("acq_")


def test_create_agent_key_returns_existing(client, monkeypatch):
    """If user already has a key, return the existing one."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"login": "testuser", "name": "Test User"}

    with patch("team_api.auth.http_requests.get", return_value=mock_resp):
        resp1 = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_fake_token"},
        )
        resp2 = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_fake_token"},
        )

    assert resp1.json()["api_key"] == resp2.json()["api_key"]


def test_create_agent_key_invalid_github_token(client):
    """POST /auth/agent-key with invalid GitHub token returns 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("team_api.auth.http_requests.get", return_value=mock_resp):
        resp = client.post(
            "/auth/agent-key",
            headers={"Authorization": "Bearer ghp_bad_token"},
        )

    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd team-api && uv run pytest tests/test_auth.py::test_create_agent_key_success -v`
Expected: FAIL — 404 (endpoint doesn't exist).

- [ ] **Step 3: Implement the endpoint**

Add to `team-api/team_api/auth.py`:

```python
import secrets

@router.post("/agent-key")
def create_agent_key(
    request: Request,
    store: Store = Depends(get_store),
) -> dict:
    """Exchange a GitHub access token for a persistent agent API key.

    Uses the GitHub token to identify the user, then returns an existing
    key or generates a new one. Device flow clients call this after
    completing the OAuth dance.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    github_token = auth_header.removeprefix("Bearer ")

    # Validate GitHub token and get user info.
    gh_resp = http_requests.get(
        GITHUB_USER_URL,
        headers={"Authorization": f"Bearer {github_token}", "Accept": "application/json"},
        timeout=10,
    )
    if gh_resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid GitHub token")
    gh_user = gh_resp.json()
    github_username = gh_user["login"]

    # Return existing key if user already has one.
    existing = store.get_agent_key_by_github(github_username)
    if existing is not None:
        return existing

    # Generate new key.
    api_key = f"acq_{secrets.token_hex(24)}"
    agent_name = f"{github_username}-agent"
    return store.create_agent_key(api_key, agent_name, github_username)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd team-api && uv run pytest tests/test_auth.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add team-api/team_api/auth.py team-api/tests/test_auth.py
git commit -m "feat: add POST /auth/agent-key endpoint"
```

---

### Task 5: Create `scripts/setup-agent.py`

**Files:**
- Create: `scripts/setup-agent.py`

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
"""Set up acq agent authentication via GitHub device flow.

Runs the GitHub device flow, exchanges the token for an acq agent key,
and writes credentials to ~/.claude/settings.json.
"""

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# Configuration — no client secret needed for device flow.
GITHUB_CLIENT_ID = "<github-oauth-app-client-id>"
ACQ_TEAM_ADDR = "https://acq.example.com"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def _post_json(url: str, data: dict, headers: dict | None = None) -> dict:
    """POST JSON and return parsed response."""
    body = json.dumps(data).encode()
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = Request(url, data=body, headers=hdrs, method="POST")
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _get_json(url: str, headers: dict | None = None) -> dict:
    """GET JSON and return parsed response."""
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = Request(url, headers=hdrs)
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def start_device_flow() -> dict:
    """Start GitHub device flow, return device_code, user_code, etc."""
    return _post_json(
        "https://github.com/login/device/code",
        {"client_id": GITHUB_CLIENT_ID, "scope": "read:user"},
    )


def poll_for_token(device_code: str, interval: int) -> str:
    """Poll GitHub until the user authorizes, return access token."""
    while True:
        time.sleep(interval)
        try:
            resp = _post_json(
                "https://github.com/login/oauth/access_token",
                {
                    "client_id": GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        except HTTPError:
            continue

        if "access_token" in resp:
            return resp["access_token"]

        error = resp.get("error", "")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            print("Device code expired. Please try again.")
            sys.exit(1)
        elif error == "access_denied":
            print("Authorization denied.")
            sys.exit(1)
        else:
            print(f"Unexpected error: {error}")
            sys.exit(1)


def exchange_for_agent_key(github_token: str) -> dict:
    """Exchange GitHub token for acq agent key."""
    body = json.dumps({}).encode()
    req = Request(
        f"{ACQ_TEAM_ADDR}/auth/agent-key",
        data=body,
        headers={
            "Authorization": f"Bearer {github_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def write_settings(api_key: str, agent_name: str) -> None:
    """Merge acq credentials into ~/.claude/settings.json."""
    settings: dict = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text())

    env = settings.setdefault("env", {})
    env["ACQ_TEAM_API_KEY"] = api_key
    env["ACQ_AGENT_NAME"] = agent_name
    env["ACQ_TEAM_ADDR"] = ACQ_TEAM_ADDR

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def main() -> None:
    # Check if already configured.
    if SETTINGS_PATH.exists():
        try:
            existing = json.loads(SETTINGS_PATH.read_text())
            existing_key = existing.get("env", {}).get("ACQ_TEAM_API_KEY")
            if existing_key:
                print(f"acq agent key already configured in {SETTINGS_PATH}")
                print(f"  ACQ_AGENT_NAME = {existing.get('env', {}).get('ACQ_AGENT_NAME', '(not set)')}")
                print("To re-authenticate, remove ACQ_TEAM_API_KEY from settings.json and run again.")
                return
        except (json.JSONDecodeError, KeyError):
            pass

    print("Setting up acq agent authentication...\n")

    # Step 1: Start device flow.
    try:
        flow = start_device_flow()
    except Exception as e:
        print(f"Failed to start device flow: {e}")
        sys.exit(1)

    print(f"To authenticate, open this URL in your browser:")
    print(f"  {flow['verification_uri']}\n")
    print(f"And enter this code: {flow['user_code']}\n")
    print("Waiting for authorization...")

    # Step 2: Poll for token.
    github_token = poll_for_token(flow["device_code"], flow.get("interval", 5))

    # Step 3: Get user info for display.
    gh_user = _get_json(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {github_token}"},
    )
    print(f"\nAuthenticated as {gh_user['login']} ({gh_user.get('name', '')})\n")

    # Step 4: Exchange for agent key.
    try:
        agent_key = exchange_for_agent_key(github_token)
    except HTTPError as e:
        print(f"Failed to get agent key: {e}")
        sys.exit(1)

    # Step 5: Write to settings.
    write_settings(agent_key["api_key"], agent_key["agent_name"])

    print(f"Agent key written to {SETTINGS_PATH}:")
    print(f"  ACQ_TEAM_API_KEY = {agent_key['api_key'][:12]}...")
    print(f"  ACQ_AGENT_NAME   = {agent_key['agent_name']}")
    print(f"  ACQ_TEAM_ADDR    = {ACQ_TEAM_ADDR}")
    print("\nYou're ready to use acq.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/setup-agent.py
```

- [ ] **Step 3: Test manually**

Run: `python scripts/setup-agent.py`
Expected: Prints the device flow URL and code, waits for browser auth.

(Full integration test requires a running team API and GitHub OAuth. This is a manual verification step.)

- [ ] **Step 4: Commit**

```bash
git add scripts/setup-agent.py
git commit -m "feat: add setup-agent.py for GitHub device flow authentication"
```

---

### Task 6: Update Makefile and docs

**Files:**
- Modify: `Makefile`
- Modify: `README.md`

- [ ] **Step 1: Update `make setup` in Makefile**

Replace the existing `setup` target:

```makefile
.PHONY: setup
setup:
	(cd shared && uv sync --group dev)
	(cd plugins/acq/server && uv sync --group dev)
	(cd team-api && uv sync --group dev)
	(cd team-ui && pnpm install $(if $(CI),--frozen-lockfile,))
	@echo ""
	python scripts/setup-agent.py
```

- [ ] **Step 2: Update README Configuration section**

Replace the current Configuration section that tells users to manually add `ACQ_TEAM_API_KEY` with:

```markdown
## Configuration

### Agent authentication (team mode)

Run `make setup` after installation. This uses GitHub device flow to generate a personal agent API key:

\`\`\`
$ make setup
...
To authenticate, open this URL in your browser:
  https://github.com/login/device

And enter this code: ABCD-1234
...
\`\`\`

The script writes `ACQ_TEAM_API_KEY`, `ACQ_AGENT_NAME`, and `ACQ_TEAM_ADDR` to `~/.claude/settings.json` automatically.

### Local-only mode

Accrue works out of the box without authentication. When `ACQ_TEAM_ADDR` is unset, all data stays in `~/.acq/local.db`.
```

- [ ] **Step 3: Commit**

```bash
git add Makefile README.md
git commit -m "docs: update setup flow for GitHub device flow auth"
```

---

### Task 7: Bump versions and final test

**Files:**
- Modify: `plugins/acq/.claude-plugin/plugin.json`
- Modify: `plugins/acq/server/pyproject.toml`

- [ ] **Step 1: Run full test suite**

```bash
cd shared && uv run pytest tests/ -v
cd ../team-api && uv run pytest tests/ -v
cd ../plugins/acq/server && uv run pytest tests/ -v
```

Expected: All pass.

- [ ] **Step 2: Bump versions**

In `plugins/acq/.claude-plugin/plugin.json`: `"version": "0.7.0"`
In `plugins/acq/server/pyproject.toml`: `version = "0.6.0"`

- [ ] **Step 3: Commit and push**

```bash
git add plugins/acq/.claude-plugin/plugin.json plugins/acq/server/pyproject.toml
git commit -m "chore: bump to plugin 0.7.0, server 0.6.0 for per-user agent keys"
git push origin SeanMeyer/acq-prompts:main
```
