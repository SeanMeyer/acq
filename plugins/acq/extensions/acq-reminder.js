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

  // A reload reuses this instance, so the flag is set from the incoming
  // session. Only a fresh one needs the reminder: a resumed, forked or
  // reloaded session already holds it, and clearing the flag there added a
  // copy every time.
  pi.on("session_start", (event) => {
    injected = !(event.reason === "startup" || event.reason === "new");
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
