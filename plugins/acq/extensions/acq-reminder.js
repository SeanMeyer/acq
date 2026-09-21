// Pi equivalent of the Claude-format SessionStart hook in ../hooks/hooks.json:
// standing guidance to search ACQ, delivered before the model has decided
// whether to load the full ACQ skill. pi's own `session_start` event is
// side-effect only and cannot contribute context, so the injection happens on
// the first `before_agent_start` of the session instead.

const REMINDER = [
  "Search ACQ before a nontrivial investigation when prior experience could",
  "save time. ACQ tools are available through the `mcp` adapter. Search returns",
  "questions only, so open relevant threads to read answers. Treat answers as",
  "leads and verify them against the current system.",
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
