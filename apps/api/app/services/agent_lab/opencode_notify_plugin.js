// GAIA Agent Lab: OpenCode notify relay (thin relay, no Python abstraction).
//
// Seeded into the sandbox at session start as `.opencode/plugins/gaia_lab_notify.js`.
// Env (injected by the seeder per session):
//   GAIA_LAB_CALLBACK_URL - full GAIA receiver URL (POST /api/v1/lab/events)
//   GAIA_LAB_TOKEN        - sandbox bearer token for the receiver
//   GAIA_LAB_SESSION_ID   - GAIA agent_lab_sessions id this sandbox run belongs to
//
// Contract (owned by the sibling GAIA-side receiver; do NOT build an endpoint here):
//   POST {GAIA_LAB_CALLBACK_URL} {session_id, kind: string, raw: object}
//   Auth: Authorization: Bearer <GAIA_LAB_TOKEN>
//
// Version-sensitive API uses (verified live against opencode v2.0.2, 2026-10-04:
// v2.0.2-as-installed REQUIRES `export default { id, setup }`, AND ignores the
// hooks object setup returns — `{ event }` handlers are never invoked (proven:
// setup side-effects ran, zero hook calls across idle/created/deleted while
// /api/plugin reported active). The wired path is `for await (... of
// ctx.event.subscribe())` inside setup (verified live; the callback form
// subscribe(fn) silently delivers nothing). If plugins stop relaying after an
// upgrade, re-probe with a catch-all subscribe loop, not the docs page.):
//   - Subscribed event.type values: `session.idle`, `permission.asked`,
//     `session.error`. Turn-scoped: strictly post-OAuth, never fires for
//     API-driven session CRUD (verified: creates/deletes emit SSE only).
// If any of the above changed upstream, re-probe live, not this file.

const KIND_BY_EVENT_TYPE = {
  "session.idle": "idle",
  "permission.asked": "permission",
  "session.error": "error",
};

async function postEvent(url, token, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`lab callback failed: ${res.status}`);
  }
}

export default {
  id: "gaia-lab-notify",
  setup: async (ctx) => {
    // Fire-and-forget: the subscribe loop below is the relay; never block setup.
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe()) {
          const kind = KIND_BY_EVENT_TYPE[event?.type];
          if (!kind) continue;
          const url = process.env.GAIA_LAB_CALLBACK_URL;
          const token = process.env.GAIA_LAB_TOKEN;
          const sessionId = process.env.GAIA_LAB_SESSION_ID;
          if (!url || !token || !sessionId) continue;
          try {
            await postEvent(url, token, {
              session_id: sessionId,
              kind,
              raw: event,
            });
          } catch {
            // Never break the agent session on a notify failure.
          }
        }
      } catch {
        // Subscribe loop died; session continues without relay.
      }
    })();
    return {};
  },
};
