#!/bin/bash
# SessionStart hook: inject acq usage guidance into the session context.
# This ensures every agent session understands what acq is and how to
# evaluate search results, without requiring CLAUDE.md configuration.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "The acq plugin provides a Q&A knowledge store from prior agent sessions. When you search acq, check: does any result's question ask the same thing you asked? If yes, apply that answer. If no result's question matches yours, these results do not answer your query — investigate independently and do not synthesize an answer from tangential results."
  }
}
EOF
