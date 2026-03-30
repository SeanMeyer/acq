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
GITHUB_CLIENT_ID = "Ov23liDo2M8HH9cnPfTB"
ACQ_TEAM_ADDR = "https://acq-team-api.us1.staging.dog"
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
