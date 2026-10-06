// GAIA: OpenCode notify relay.
//
// Seeded once per sandbox at ~/agents/config/opencode/plugins/gaia_notify.js and
// loaded through OPENCODE_CONFIG_DIR, so it works from any working directory.
// Each forwarded event is piped as {kind, raw} into gaia-hook (path rendered at
// seed time), which saves the agents' home and then POSTs the event to GAIA with
// the run's GAIA_LAB_CALLBACK_URL / GAIA_LAB_TOKEN from this process's env.
//
// One file serves both plugin APIs, each verified live (2026-10-04):
//   OpenCode 1.x loads `{ server }` and calls the `event` hook it returns.
//   OpenCode 2.x loads `{ id, setup }`, ignores returned hooks, and delivers
//   events only through `for await (... of ctx.event.subscribe())`.
// Each version calls only its own entry point, so an event is posted once.
// Every forwarded event runs the owning todo, so only "the agent stopped,
// is asking, or failed" is forwarded; streaming chatter never is.
// If relaying stops after an upgrade, re-probe live, not the docs page.

import { spawn } from "node:child_process";

const GAIA_HOOK = "{{GAIA_HOOK}}";
// gaia-hook bounds its own save and POST; this only stops a wedged child.
const HOOK_DEADLINE_MS = Number("{{HOOK_TIMEOUT_SECONDS}}") * 1000;

// 1.x and 2.x name the same moments differently. Seen firing live: 1.x
// session.idle/session.error, 2.x session.execution.failed; the rest are taken
// from each version's own event catalog and still need a real turn to observe.
const KIND_BY_EVENT_TYPE = {
  "session.idle": "idle",
  "session.error": "error",
  "question.asked": "question",
  "permission.asked": "permission",
  "permission.updated": "permission",
  "session.execution.succeeded": "finished",
  "session.execution.failed": "error",
  "session.execution.interrupted": "interrupted",
};

// Each relay runs the owning todo, so post one event per moment. A turn's end
// arrives as several events (1.18: session.error then session.idle twice), so
// only the first end per session inside the window is posted. Sub-agent child
// sessions (parentID set) are the agent's own business: never posted.
// State is process-wide, not module scope: OpenCode evaluates the plugin once
// per instance.
const REPEAT_WINDOW_MS = 10000;
const TURN_END_KINDS = new Set(["idle", "error", "finished", "interrupted"]);
const state = (globalThis[Symbol.for("gaia-lab-notify.state")] ??= {
  recent: new Map(),
  childSessions: new Set(),
});

function sessionOf(event) {
  const properties = event.properties ?? {};
  return properties.sessionID ?? properties.info?.id;
}

function rememberChildSession(event) {
  const info = event.properties?.info;
  if (info?.id && info.parentID) state.childSessions.add(info.id);
}

function isRepeat(event, kind) {
  const key = TURN_END_KINDS.has(kind)
    ? `turn-end:${sessionOf(event)}`
    : `${event.type}:${JSON.stringify(event.properties ?? {})}`;
  const now = Date.now();
  for (const [seen, at] of state.recent) {
    if (now - at > REPEAT_WINDOW_MS) state.recent.delete(seen);
  }
  if (state.recent.has(key)) return true;
  state.recent.set(key, now);
  return false;
}

function runHook(body) {
  return new Promise((resolve) => {
    const child = spawn(GAIA_HOOK, [], { stdio: ["pipe", "ignore", "inherit"] });
    const deadline = setTimeout(() => {
      console.error("gaia-lab-notify: gaia-hook timed out; killing it");
      child.kill("SIGKILL");
    }, HOOK_DEADLINE_MS);
    child.on("error", (error) => {
      clearTimeout(deadline);
      console.error(`gaia-lab-notify: gaia-hook failed to start: ${error}`);
      resolve();
    });
    child.on("close", () => {
      clearTimeout(deadline);
      resolve();
    });
    child.stdin.end(JSON.stringify(body));
  });
}

async function relay(event) {
  if (!event?.type) return;
  rememberChildSession(event);
  const kind = KIND_BY_EVENT_TYPE[event.type];
  if (!kind) return;
  if (state.childSessions.has(sessionOf(event)) || isRepeat(event, kind)) return;
  // Never break the agent session on a relay failure; gaia-hook logs its own.
  await runHook({ kind, raw: event });
}

export default {
  id: "gaia-lab-notify",
  server: async () => ({
    event: async ({ event }) => relay(event),
  }),
  setup: async (ctx) => {
    // 1.x also calls setup, with no event stream; its events arrive via server().
    if (typeof ctx?.event?.subscribe !== "function") return {};
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe()) {
          await relay(event);
        }
      } catch (error) {
        console.error(`gaia-lab-notify: event stream ended: ${error}`);
      }
    })();
    return {};
  },
};
