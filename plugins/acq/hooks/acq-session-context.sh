#!/bin/bash
# SessionStart hook: add the small amount of standing guidance needed before
# the model has decided whether to load the full ACQ skill.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Search ACQ before a nontrivial investigation when prior experience could save time. Search returns questions only, so open relevant threads to read answers. Treat answers as leads and verify them against the current system."
  }
}
EOF
