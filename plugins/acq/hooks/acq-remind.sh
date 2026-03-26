#!/bin/bash
# PreToolUse hook for Agent/Explore tools.
# Reminds Claude to search acq for THIS SPECIFIC sub-question,
# not just once at the start of the session.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null)

case "$TOOL_NAME" in
  Agent|Explore)
    PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // .tool_input.description // ""' 2>/dev/null | head -c 200)
    echo "Before exploring: search acq for this specific question first. Even if you searched acq earlier in this conversation, this sub-task may have its own answer. Query: ${PROMPT:0:100}" >&2
    ;;
esac

exit 0
