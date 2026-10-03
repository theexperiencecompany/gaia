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
// Version-sensitive API uses (see https://opencode.ai/docs/plugins):
//   - Plugin export shape: module exports an async function receiving context
//     ({ project, client, $, directory, worktree }) and returning a hooks object.
//   - The `event:` hook receives `{ event }` and dispatches on `event.type`.
//   - Subscribed event.type values: `session.idle`, `permission.asked`,
//     `session.error` (all listed under Session/Permission Events on the docs page).
//   - `$` is Bun's shell API (unused here; fetch is used instead).
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

export const GaiaLabNotify = async (_ctx) => {
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
};
