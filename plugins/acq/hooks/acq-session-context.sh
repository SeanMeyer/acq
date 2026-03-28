#!/bin/bash
# SessionStart hook: inject acq usage guidance into the session context.
# This ensures every agent session understands what acq is and how to
# evaluate search results, without requiring CLAUDE.md configuration.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "The acq plugin provides a Q&A knowledge store from prior agent sessions. Search returns questions only — call get_thread with all relevant question IDs to read answers. Results that mention your topic are not answers about your topic — always investigate independently too. Do not let acq results narrow your investigation."
  }
}
EOF
