/**
 * Server-side setup the screen flows need and the UI cannot reach: the dev
 * user's approval preferences, an approval's expiry, and reads of what the API
 * holds. Every call rides the dev auth bypass, so it acts as the dev user.
 */

import { execFileSync } from "node:child_process";
import { API_BASE_URL } from "./harness";

const MONGO_URI = process.env.E2E_MONGO_URI ?? "mongodb://localhost:27017/GAIA";

async function api(path: string, init: RequestInit = {}): Promise<void> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw new Error(
      `${init.method ?? "GET"} ${path} failed (${response.status}): ${await response.text()}`,
    );
  }
}

/**
 * Ask before every call of `askFor`; with none, never ask. always_allow gates
 * nothing, overrides included, so asking takes always_ask.
 */
export async function askBefore(askFor: string[]): Promise<void> {
  await api("/approvals/preferences", {
    method: "PUT",
    body: JSON.stringify({
      mode: askFor.length > 0 ? "always_ask" : "always_allow",
      tool_overrides: Object.fromEntries(askFor.map((tool) => [tool, true])),
      never_auto_tools: [],
    }),
  });
}

export function conversationIdOf(url: string): string {
  const match = url.match(/\/c\/([0-9a-f-]{36})/);
  if (!match) throw new Error(`No conversation id in ${url}`);
  return match[1];
}

/**
 * Backdate the conversation's open approval past its expiry, so the worker's
 * conversation sweep (every minute) expires it as it would after hours unanswered.
 */
export function seedInAppNotification(email: string, title: string): void {
  // In chat, send_notification folds into the reply it would duplicate, so an
  // in-app notification is stored the way the delivery service stores one.
  const script = `
    const user = db.users.findOne({ email: ${JSON.stringify(email)} });
    if (!user) throw new Error("no dev user");
    const id = new UUID().toString().replace(/^UUID\\("|"\\)$/g, "");
    const now = new Date();
    const channels = [{ channel_type: "inapp", status: "delivered", delivered_at: now,
      error_message: null, retry_count: 0, skipped: false }];
    const content = { title: ${JSON.stringify(title)}, body: "e2e", actions: [] };
    db.notifications.insertOne({ id, user_id: String(user._id), status: "delivered",
      created_at: now, delivered_at: now, read_at: null, channels,
      original_request: { id, user_id: String(user._id), source: "workflow_completed",
        type: "info", priority: 3, content, metadata: {}, created_at: now,
        channels: [{ channel_type: "inapp", enabled: true, priority: 1, config: {} }],
        message_class: "routine" } });`;
  execFileSync("mongosh", [MONGO_URI, "--quiet", "--eval", script]);
}

export function backdateApproval(conversationId: string): void {
  const script = `
    const r = db.conversation_entries.updateMany(
      { conversation_id: ${JSON.stringify(conversationId)}, kind: "approval_requested" },
      { $set: { expires_at: new Date(Date.now() - 24 * 3600 * 1000) } });
    if (r.matchedCount === 0) throw new Error("no approval_requested entry to backdate");`;
  execFileSync("mongosh", [MONGO_URI, "--quiet", "--eval", script]);
}
