// GAIA Agent Lab: OpenCode notify relay (thin relay, no Python abstraction).
//
// Seeded per run as `<run>/.opencode/plugins/gaia_lab_notify.js`, loaded through
// OPENCODE_CONFIG_DIR=<run>/.opencode so it works from any working directory.
// Env (the run env, injected at launch):
//   GAIA_LAB_CALLBACK_URL - full GAIA receiver URL (POST /api/v1/lab/events)
//   GAIA_LAB_TOKEN        - the run's bearer token; it alone names the run
//
// Contract (owned by the GAIA-side receiver; do NOT build an endpoint here):
//   POST {GAIA_LAB_CALLBACK_URL} {kind: string, raw: object}
//   Auth: Authorization: Bearer <GAIA_LAB_TOKEN>
//
// One file serves both plugin APIs, each verified live (2026-10-04):
//   OpenCode 1.x loads `{ server }` and calls the `event` hook it returns.
//   OpenCode 2.x loads `{ id, setup }`, ignores returned hooks, and delivers
//   events only through `for await (... of ctx.event.subscribe())`.
// Each version calls only its own entry point, so an event is posted once.
// Every forwarded event runs the owning todo, so only "the agent stopped,
// is asking, or failed" is forwarded; streaming chatter never is.
// If relaying stops after an upgrade, re-probe live, not the docs page.

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

async function relay(event) {
  if (!event?.type) return;
  rememberChildSession(event);
  const kind = KIND_BY_EVENT_TYPE[event.type];
  const url = process.env.GAIA_LAB_CALLBACK_URL;
  const token = process.env.GAIA_LAB_TOKEN;
  if (!kind || !url || !token) return;
  if (state.childSessions.has(sessionOf(event)) || isRepeat(event, kind)) return;
  try {
    const res = await fetch(url, {
      method: "POST",
      // Same 15s budget as the Claude hook pushes: a hung callback must fail
      // here instead of stalling the agent's event loop.
      signal: AbortSignal.timeout(15000),
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ kind, raw: event }),
    });
    if (!res.ok) {
      console.error(`gaia-lab-notify: callback answered ${res.status}`);
    }
  } catch (error) {
    // Never break the agent session on a notify failure; say so in its log.
    console.error(`gaia-lab-notify: callback failed: ${error}`);
  }
}

export default {
  id: "gaia-lab-notify",
  server: async () => ({
    event: async ({ event }) => relay(event),
  }),
  setup: async (ctx) => {
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
