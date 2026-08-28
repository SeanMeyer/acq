#!/usr/bin/env python3
"""Set up acq agent authentication via GitHub device flow.

Runs the GitHub device flow, exchanges the resulting token for an acq agent
key, and writes credentials to ~/.claude/settings.json.

Two settings are specific to your deployment and have no sensible defaults:

    --team-addr / ACQ_TEAM_ADDR
        Base URL of your team API, e.g. https://acq.example.com

    --client-id / ACQ_GITHUB_CLIENT_ID
        Client ID of the GitHub OAuth app that deployment uses. The app must
        have device flow enabled.

Example:

    ACQ_TEAM_ADDR=https://acq.example.com \\
    ACQ_GITHUB_CLIENT_ID=Ov23li... \\
    python scripts/setup-agent.py
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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


def start_device_flow(client_id: str) -> dict:
    """Start GitHub device flow, return device_code, user_code, etc."""
    return _post_json(
        "https://github.com/login/device/code",
        {"client_id": client_id, "scope": "read:user"},
    )


def poll_for_token(client_id: str, device_code: str, interval: int) -> str:
    """Poll GitHub until the user authorizes, return access token."""
    while True:
        time.sleep(interval)
        try:
            resp = _post_json(
                "https://github.com/login/oauth/access_token",
                {
                    "client_id": client_id,
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


def exchange_for_agent_key(team_addr: str, github_token: str) -> dict:
    """Exchange GitHub token for acq agent key."""
    body = json.dumps({}).encode()
    req = Request(
        f"{team_addr}/auth/agent-key",
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


def write_settings(team_addr: str, api_key: str, agent_name: str) -> None:
    """Merge acq credentials into ~/.claude/settings.json."""
    settings: dict = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text())

    env = settings.setdefault("env", {})
    env["ACQ_TEAM_API_KEY"] = api_key
    env["ACQ_AGENT_NAME"] = agent_name
    env["ACQ_TEAM_ADDR"] = team_addr

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--team-addr",
        default=os.environ.get("ACQ_TEAM_ADDR", ""),
        help="Base URL of the team API (env: ACQ_TEAM_ADDR)",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("ACQ_GITHUB_CLIENT_ID", ""),
        help="GitHub OAuth app client ID with device flow enabled (env: ACQ_GITHUB_CLIENT_ID)",
    )
    args = parser.parse_args()

    missing = []
    if not args.team_addr:
        missing.append("--team-addr (or ACQ_TEAM_ADDR)")
    if not args.client_id:
        missing.append("--client-id (or ACQ_GITHUB_CLIENT_ID)")
    if missing:
        parser.error(
            "missing required deployment settings: "
            + ", ".join(missing)
            + "\nThese are specific to your acq deployment; see the module docstring."
        )

    args.team_addr = args.team_addr.rstrip("/")
    return args


def main() -> None:
    args = _parse_args()

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
        flow = start_device_flow(args.client_id)
    except Exception as e:
        print(f"Failed to start device flow: {e}")
        sys.exit(1)

    print("To authenticate, open this URL in your browser:")
    print(f"  {flow['verification_uri']}\n")
    print(f"And enter this code: {flow['user_code']}\n")
    print("Waiting for authorization...")

    # Step 2: Poll for token.
    github_token = poll_for_token(args.client_id, flow["device_code"], flow.get("interval", 5))

    # Step 3: Get user info for display.
    gh_user = _get_json(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {github_token}"},
    )
    print(f"\nAuthenticated as {gh_user['login']} ({gh_user.get('name', '')})\n")

    # Step 4: Exchange for agent key.
    try:
        agent_key = exchange_for_agent_key(args.team_addr, github_token)
    except HTTPError as e:
        print(f"Failed to get agent key: {e}")
        sys.exit(1)

    # Step 5: Write to settings.
    write_settings(args.team_addr, agent_key["api_key"], agent_key["agent_name"])

    print(f"Agent key written to {SETTINGS_PATH}:")
    print(f"  ACQ_TEAM_API_KEY = {agent_key['api_key'][:12]}...")
    print(f"  ACQ_AGENT_NAME   = {agent_key['agent_name']}")
    print(f"  ACQ_TEAM_ADDR    = {args.team_addr}")
    print("\nYou're ready to use acq.")


if __name__ == "__main__":
    main()
