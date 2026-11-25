// Pi equivalent of the Claude-format SessionStart hook in ../hooks/hooks.json:
// standing guidance to search ACQ, delivered before the model has decided
// whether to load the full ACQ skill. pi's own `session_start` event is
// side-effect only and cannot contribute context, so the injection happens on
// `before_agent_start`, once per session branch that can search ACQ.

// Shorter than plugins/acq/guidance/agents-block.md by design: this fires once
// per session to catch the model before it explores, so it carries only the
// reason to search. Matches ../hooks/acq-session-context.sh apart from the
// pi-only mcp sentence below. Edit the two together.
const REMINDER = [
  "Search ACQ before a nontrivial investigation. The dead end ahead of you may",
  "already be mapped, and rediscovering it looks exactly like discovering it,",
  "which is why the cost goes unnoticed. ACQ tools are under the `mcp` adapter.",
].join(" ");

const CUSTOM_TYPE = "acq-reminder";

// pi-mcp-adapter's names for a tool that reaches the acq server: its gateway,
// the server's proxy, direct tools under the default "server" prefix, and tools
// under the "mcp" prefix or loaded through tool search.
const reachesAcq = (name) =>
  name === "mcp" || name === "mcp__acq" || name.startsWith("acq_") || name.startsWith("mcp__acq__");

export default function (pi) {
  // Ask the session rather than tracking state here. The start reason doesn't
  // say whether the reminder is already present: `pi -c` and `--session`
  // report "startup" for a session that holds it, and a fork from before the
  // first prompt reports "fork" for one that doesn't. The injected message is
  // stored as a custom_message entry, so the branch answers it exactly.
  pi.on("before_agent_start", async (_event, ctx) => {
    // A session that can't search ACQ, such as a tool-less subagent, would
    // read the reminder as part of its task.
    if (!pi.getActiveTools().some(reachesAcq)) return;
    const present = ctx.sessionManager
      .getBranch()
      .some((entry) => entry.type === "custom_message" && entry.customType === CUSTOM_TYPE);
    if (present) return;
    return {
      message: {
        customType: CUSTOM_TYPE,
        content: REMINDER,
        display: false,
      },
    };
  });
}
