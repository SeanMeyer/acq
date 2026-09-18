// Pi equivalent of the Claude-format SessionStart hook in ../hooks/hooks.json:
// standing guidance to search ACQ, delivered before the model has decided
// whether to load the full ACQ skill. pi's own `session_start` event is
// side-effect only and cannot contribute context, so the injection happens on
// the first `before_agent_start` of the session instead.

// Shorter than plugins/acq/guidance/agents-block.md by design: this fires once
// per session to catch the model before it explores, so it carries only the
// reason to search. Matches ../hooks/acq-session-context.sh apart from the
// pi-only mcp sentence below. Edit the two together.
const REMINDER = [
  "Search ACQ before a nontrivial investigation. The dead end ahead of you may",
  "already be mapped, and rediscovering it looks exactly like discovering it,",
  "which is why the cost goes unnoticed. ACQ tools are under the `mcp` adapter.",
].join(" ");

export default function (pi) {
  let injected = false;

  // Extensions are reloaded and rebound per session, but a reload reuses this
  // instance, so the flag has to be cleared for the incoming session.
  pi.on("session_start", () => {
    injected = false;
  });

  pi.on("before_agent_start", async () => {
    if (injected) return;
    injected = true;
    return {
      message: {
        customType: "acq-reminder",
        content: REMINDER,
        display: false,
      },
    };
  });
}
