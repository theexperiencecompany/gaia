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
// v2.0.2-as-installed REQUIRES `export default { id, setup }` and rejects the
// named-export function shape the docs page still shows. If plugins stop
// loading after an upgrade, re-probe with a minimal default-export probe and
// check /api/plugin for state active.):
//   - Default export { id, setup }: setup(ctx) returns the hooks object.
//   - The `event:` hook receives `{ event }` and dispatches on `event.type`.
//   - Subscribed event.type values: `session.idle`, `permission.asked`,
//     `session.error` (docs event list; relay of idle/permission UNVERIFIED
//     without provider auth — session CRUD works pre-auth, model turns don't).
// If any of the above changed upstream, check --help / the docs page, not this file.

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
  setup: async (_ctx) => {
    return {
      // Version-sensitive: `event:` hook shape per https://opencode.ai/docs/plugins.
      event: async ({ event }) => {
        const kind = KIND_BY_EVENT_TYPE[event?.type];
        if (!kind) return;
        const url = process.env.GAIA_LAB_CALLBACK_URL;
        const token = process.env.GAIA_LAB_TOKEN;
        const sessionId = process.env.GAIA_LAB_SESSION_ID;
        if (!url || !token || !sessionId) return;
        try {
          await postEvent(url, token, {
            session_id: sessionId,
            kind,
            raw: event,
          });
        } catch {
          // Never break the agent session on a notify failure.
        }
      },
    };
  },
};
