#!/bin/bash
# SessionStart hook: inject acq usage guidance into the session context.
# This ensures every agent session understands what acq is and how to
# evaluate search results, without requiring CLAUDE.md configuration.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "The acq plugin provides a Q&A knowledge store from prior agent sessions. When you search acq, results are specific Q&A entries that matched your keywords — not comprehensive knowledge. Use judgement: if a result directly answers your question, apply it. If results are tangential (related topic but different question), use them as background context for your own investigation, not as the answer."
  }
}
EOF
