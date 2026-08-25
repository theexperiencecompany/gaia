/**
 * Drives the {@link HarnessAdapter} end to end: mints + links a dev user via the
 * backend's dev endpoints, boots the real bot pipeline against a running API,
 * injects messages, and (for scenarios) checks transcript assertions.
 *
 * All backend calls go through the same real code paths a production bot uses;
 * the only dev-only surface touched is the identity endpoints (`/api/v1/dev/*`),
 * which exist solely to create the platform link the bot pipeline authenticates
 * against.
 */

import type { PlatformName } from "@gaia/shared";
import { HarnessAdapter } from "./adapter";
import { isEmulatablePlatform, resolveEmulation } from "./emulation";
import type { Scenario, ScenarioAssertion } from "./scenario.types";
import { TranscriptRecorder } from "./transcript";
import type { TranscriptEvent } from "./transcript.types";

/** Default API port, matching `apps/api/project.json`'s `${API_PORT:-8000}`. */
const DEFAULT_API_PORT = "8000";

/**
 * Resolves the API base URL: explicit arg → `GAIA_API_URL` → `API_PORT` on
 * localhost. The `API_PORT` step is what makes a worktree work unattended —
 * `mise run wt:env` puts this worktree's port in `.env.worktree`, so `gaia-sim`
 * targets its own API instead of whatever process owns port 8000.
 */
export function resolveApiUrl(explicit?: string): string {
  return (
    explicit ??
    process.env.GAIA_API_URL ??
    `http://localhost:${process.env.API_PORT ?? DEFAULT_API_PORT}`
  );
}

/** Shape returned by `POST /api/v1/dev/users`. */
interface DevUser {
  id: string;
  email: string;
  name: string;
}

/** Identity of a minted + linked dev user for one emulated platform. */
export interface LinkedDevUser {
  /** Backend user id. */
  userId: string;
  email: string;
  name: string;
  /** Platform-native user id the bot pipeline authenticates against. */
  platformUserId: string;
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    // A hung API (container not ready, deadlock) must fail the run loudly,
    // not hang linkDevUser/sendOneShot/runScenario forever.
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    const suffix = detail ? `: ${detail}` : "";
    throw new Error(`${url} returned ${res.status} ${res.statusText}${suffix}`);
  }
  return (await res.json()) as T;
}

/**
 * Mints (idempotently) the dev user and links the emulated platform, returning
 * the platform-native user id (`dev-<platform>-<userId>`) the bot pipeline keys
 * auth on. Uses only the real dev endpoints — no direct DB writes.
 */
export async function linkDevUser(
  apiUrl: string,
  email: string,
  platform: PlatformName,
): Promise<LinkedDevUser> {
  const user = await postJson<DevUser>(`${apiUrl}/api/v1/dev/users`, { email });
  const seeded = await postJson<{ platform_user_ids: Record<string, string> }>(
    `${apiUrl}/api/v1/dev/seed`,
    {
      email,
      platform_links: [platform],
    },
  );
  // The seeded id is the seed endpoint's contract — never re-derive its format.
  const platformUserId = seeded.platform_user_ids[platform];
  if (!platformUserId) {
    throw new Error(
      `/dev/seed did not return a platform_user_id for '${platform}' — got: ${JSON.stringify(seeded.platform_user_ids)}`,
    );
  }
  return {
    userId: user.id,
    email: user.email,
    name: user.name,
    platformUserId,
  };
}

/**
 * Keeps the booted adapter — and with it the real outbound RabbitMQ consumer —
 * alive for `settleMs` after a turn's reply stream closes, so deliveries the
 * backend publishes *after* the stream are recorded in that turn's events.
 *
 * A handoff turn is exactly this shape: the SSE stream ends on the preamble
 * ("one sec"), and the executor's narrated answer is published to the platform
 * queue seconds later. Shutting down in between does not lose the message — it
 * strands it in the durable queue for whichever `gaia-sim` boots next.
 */
function settle(settleMs: number): Promise<void> {
  if (settleMs <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, settleMs));
}

/** Boots a HarnessAdapter emulating `platform`, targeting `apiUrl`. */
async function bootAdapter(
  platform: PlatformName,
  apiUrl: string,
  transcript: TranscriptRecorder,
): Promise<HarnessAdapter> {
  // Set first so the bot config loader (dotenv does not override existing env)
  // points the real GaiaClient at the same API the dev endpoints used.
  process.env.GAIA_API_URL = apiUrl;
  const adapter = new HarnessAdapter(resolveEmulation(platform), transcript);
  await adapter.boot([]);
  return adapter;
}

/** Result of a one-shot `gaia-sim send`. */
export interface SendResult {
  platform: PlatformName;
  user: LinkedDevUser;
  transcript: TranscriptRecorder;
}

/**
 * One-shot: mint + link the user, boot the pipeline, inject a single message,
 * and return the recorded transcript. The adapter is always shut down, even if
 * the turn throws.
 */
export async function sendOneShot(params: {
  apiUrl: string;
  emulate: PlatformName;
  email: string;
  message: string;
  channelId?: string;
  /** See {@link settle} — 0 (the default) shuts down as soon as the stream ends. */
  settleMs?: number;
}): Promise<SendResult> {
  const { apiUrl, emulate, email, message, channelId, settleMs = 0 } = params;
  const user = await linkDevUser(apiUrl, email, emulate);
  const transcript = new TranscriptRecorder(emulate);
  const adapter = await bootAdapter(emulate, apiUrl, transcript);
  try {
    await adapter.simulateMessage(user.platformUserId, message, { channelId });
    await settle(settleMs);
  } finally {
    await adapter.shutdown("harness").catch(() => undefined);
  }
  return { platform: emulate, user, transcript };
}

/** Outcome of one scenario run. */
export interface ScenarioResult {
  name: string;
  platform: PlatformName;
  passed: boolean;
  failures: string[];
  transcript: TranscriptRecorder;
}

/**
 * Runs a multi-turn scenario: one boot, sequential turns, per-turn assertions
 * evaluated against the events that turn produced.
 */
export async function runScenario(
  scenario: Scenario,
  apiUrl: string,
  settleMsOverride?: number,
): Promise<ScenarioResult> {
  if (!isEmulatablePlatform(scenario.emulate)) {
    throw new Error(
      `Scenario "${scenario.name}" emulates unknown platform "${scenario.emulate}"`,
    );
  }
  const platform = scenario.emulate;
  const user = await linkDevUser(apiUrl, scenario.user, platform);
  const transcript = new TranscriptRecorder(platform);
  const adapter = await bootAdapter(platform, apiUrl, transcript);
  const failures: string[] = [];

  try {
    for (const [index, turn] of scenario.turns.entries()) {
      const before = transcript.getEvents().length;
      await adapter.simulateMessage(user.platformUserId, turn.send, {
        channelId: turn.channelId,
      });
      // Settle BEFORE slicing: a late outbound delivery belongs to the turn
      // that caused it, and its assertions must be able to see it.
      await settle(turn.settleMs ?? settleMsOverride ?? scenario.settleMs ?? 0);
      const turnEvents = transcript.getEvents().slice(before);
      for (const assertion of turn.expect ?? []) {
        for (const failure of evaluateAssertion(turnEvents, assertion)) {
          failures.push(`turn ${index + 1} ("${turn.send}"): ${failure}`);
        }
      }
    }
  } finally {
    await adapter.shutdown("harness").catch(() => undefined);
  }

  return {
    name: scenario.name,
    platform,
    passed: failures.length === 0,
    failures,
    transcript,
  };
}

/** All text-bearing events carry a `text` field; this narrows to it. */
function eventText(event: TranscriptEvent): string | null {
  return "text" in event && typeof event.text === "string" ? event.text : null;
}

/**
 * Checks one assertion against a turn's events, returning a list of human
 * readable failure messages (empty when the assertion holds).
 */
function evaluateAssertion(
  events: readonly TranscriptEvent[],
  assertion: ScenarioAssertion,
): string[] {
  const failures: string[] = [];
  const sends = events.filter((e) => e.type === "send");
  // Text assertions must only see DELIVERED output — the inbound event carries
  // the user's own message, which would make `contains` pass trivially and
  // `maxBubbleLength` fail on long inputs.
  const delivered = events.filter(
    (e) =>
      e.type === "send" || e.type === "edit" || e.type === "outbound-delivery",
  );

  if (
    assertion.bubbleCount !== undefined &&
    sends.length !== assertion.bubbleCount
  ) {
    failures.push(
      `expected ${assertion.bubbleCount} bubble(s), got ${sends.length}`,
    );
  }
  if (
    assertion.minBubbles !== undefined &&
    sends.length < assertion.minBubbles
  ) {
    failures.push(
      `expected ≥${assertion.minBubbles} bubble(s), got ${sends.length}`,
    );
  }
  if (assertion.contains !== undefined) {
    const found = delivered.some((e) =>
      eventText(e)?.includes(assertion.contains as string),
    );
    if (!found) {
      failures.push(`no delivered text contains "${assertion.contains}"`);
    }
  }
  if (assertion.maxBubbleLength !== undefined) {
    const over = delivered.filter((e) => {
      const text = eventText(e);
      return (
        text !== null && text.length > (assertion.maxBubbleLength as number)
      );
    });
    if (over.length > 0) {
      failures.push(
        `${over.length} message(s) exceed maxBubbleLength ${assertion.maxBubbleLength}`,
      );
    }
  }
  if (assertion.eventTypes !== undefined) {
    const present = new Set(events.map((e) => e.type));
    for (const wanted of assertion.eventTypes) {
      if (!present.has(wanted as TranscriptEvent["type"])) {
        failures.push(`expected an event of type "${wanted}"`);
      }
    }
  }
  return failures;
}
