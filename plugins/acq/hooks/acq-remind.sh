#!/bin/bash
# PreToolUse hook for Agent/Explore tools.
# Reminds Claude to search acq before launching expensive exploration.
#
# The hook reads the tool input from stdin (JSON with tool_name and tool_input).
# It prints a reminder to stderr, which Claude sees as hook feedback.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null)

# Only remind for exploration-type tools
case "$TOOL_NAME" in
  Agent|Explore)
    echo "acq reminder: Have you searched acq for prior knowledge before exploring? A quick search may save minutes of exploration." >&2
    ;;
esac

exit 0
