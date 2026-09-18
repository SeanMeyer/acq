#!/bin/bash
# SessionStart hook: add the small amount of standing guidance needed before
# the model has decided whether to load the full ACQ skill.
#
# Same nudge as plugins/acq/extensions/acq-reminder.js, which serves hosts that
# cannot run this hook. That copy adds one pi-only sentence about the mcp
# adapter and should otherwise match. Edit the two together.

cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Search ACQ before a nontrivial investigation. The dead end ahead of you may already be mapped, and rediscovering it looks exactly like discovering it, which is why the cost goes unnoticed."
  }
}
EOF
