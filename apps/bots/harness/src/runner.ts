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

import type { QuietHours } from "@gaia/shared/api/generated";
import { allCommands, type PlatformName, withTimeout } from "@gaia/shared/bots";
import { HarnessAdapter } from "./adapter";
import { isEmulatablePlatform, resolveEmulation } from "./emulation";
import type {
  BurstMessage,
  Scenario,
  ScenarioAssertion,
  ScenarioTurn,
} from "./scenario.types";
import { TranscriptRecorder } from "./transcript";
import type { TranscriptEvent } from "./transcript.types";

/** Default API port, matching `apps/api/project.json`'s `${API_PORT:-8000}`. */
const DEFAULT_API_PORT = "8000";

/** How long a restart turn waits for the reply to reach its restartAfterSends-th message. */
const RESTART_TRIGGER_TIMEOUT_MS = 60_000;

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
      email: user.email,
      platform_links: [platform],
      // Every bot reply is paid-only; a scenario user without Pro only ever sees the paywall.
      pro: true,
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

/** Calls the API as the dev user and returns its JSON body, failing the run on any refusal. */
async function asDevUser<T>(
  apiUrl: string,
  email: string,
  method: "GET" | "PUT" | "PATCH",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${apiUrl}${path}`, {
    method,
    headers: { "content-type": "application/json", "X-Dev-User": email },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    throw new Error(
      `${method} ${path} for ${email} returned ${res.status}: ${await res.text()}`,
    );
  }
  return (await res.json()) as T;
}

/**
 * Asks before every call of `askFor` and before no other: the per-tool asks sit
 * on top of "allow always", which is how a user sets them in settings.
 */
async function askBefore(
  apiUrl: string,
  email: string,
  askFor: readonly string[],
): Promise<void> {
  await asDevUser(apiUrl, email, "PUT", "/api/v1/approvals/preferences", {
    mode: "always_allow",
    tool_overrides: Object.fromEntries(askFor.map((tool) => [tool, true])),
    never_auto_tools: [],
  });
}

/**
 * Turns the user's quiet hours off, so a proactive delivery (a todo run's question)
 * arrives whatever the hour the run happens at, not held for the user's morning.
 */
async function quietHoursOff(apiUrl: string, email: string): Promise<void> {
  const path = "/api/v1/user/quiet-hours";
  const hours = await asDevUser<QuietHours>(apiUrl, email, "GET", path);
  await asDevUser<QuietHours>(apiUrl, email, "PATCH", path, {
    ...hours,
    enabled: false,
  } satisfies QuietHours);
}

/**
 * Keeps the adapter (and its outbound RabbitMQ consumer) alive `settleMs` after a
 * turn's stream closes, so deliveries published afterward land in that turn's
 * events. A handoff turn closes SSE on the preamble while the real answer
 * publishes later; shutting down early strands it in the queue instead of losing it.
 * SIGTERM ends the window early (see below).
 */
function settle(settleMs: number, cutShort: Promise<void>): Promise<void> {
  if (settleMs <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, settleMs);
    void cutShort.then(() => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * Resolves on the first SIGTERM. A driver that can see the run finish (its job
 * state, its final delivery) sends it to end the send early with the transcript
 * still written, whether the turn is still streaming or already settling.
 */
function terminationRequested(): Promise<void> {
  return new Promise((resolve) => {
    process.once("SIGTERM", () => resolve());
  });
}

/** Boots a HarnessAdapter emulating `platform`, targeting `apiUrl`. */
async function bootAdapter(
  platform: PlatformName,
  apiUrl: string,
  transcript: TranscriptRecorder,
  consumesOutbound = true,
): Promise<HarnessAdapter> {
  // Set first so the bot config loader (dotenv does not override existing env)
  // points the real GaiaClient at the same API the dev endpoints used.
  process.env.GAIA_API_URL = apiUrl;
  // A dev shell's BOT_SERVER_PORT is the real bot's port; the harness serves on
  // a free one so two senders (and the real bot) never collide.
  delete process.env.BOT_SERVER_PORT;
  const adapter = new HarnessAdapter(resolveEmulation(platform), transcript, {
    consumesOutbound,
  });
  try {
    // The same commands the real bots register, so /stop, /new and /help behave as they do live.
    await adapter.boot(allCommands);
  } catch (error: unknown) {
    // Boot can fail after the outbound consumer is up; left running it keeps
    // the process alive and silently takes another run's replies.
    await adapter.shutdown("harness").catch(() => undefined);
    throw error;
  }
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
  /** False for a message into a conversation another sender already consumes for. */
  consumesOutbound?: boolean;
  /** Where each transcript event is written as it is recorded. */
  outPath?: string;
}): Promise<SendResult> {
  const {
    apiUrl,
    emulate,
    email,
    message,
    channelId,
    settleMs = 0,
    consumesOutbound = true,
    outPath,
  } = params;
  const user = await linkDevUser(apiUrl, email, emulate);
  const transcript = new TranscriptRecorder(emulate, outPath);
  const adapter = await bootAdapter(
    emulate,
    apiUrl,
    transcript,
    consumesOutbound,
  );
  const cutShort = terminationRequested();
  try {
    await Promise.race([
      adapter
        .simulateMessage(user.platformUserId, message, { channelId })
        .then(() => adapter.settleTurn()),
      cutShort,
    ]);
    await settle(settleMs, cutShort);
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
  outPath?: string,
): Promise<ScenarioResult> {
  if (!isEmulatablePlatform(scenario.emulate)) {
    throw new Error(
      `Scenario "${scenario.name}" emulates unknown platform "${scenario.emulate}"`,
    );
  }
  const platform = scenario.emulate;
  const user = await linkDevUser(apiUrl, scenario.user, platform);
  await askBefore(apiUrl, user.email, scenario.askBefore ?? []);
  await quietHoursOff(apiUrl, user.email);
  const transcript = new TranscriptRecorder(platform, outPath);
  let adapter = await bootAdapter(platform, apiUrl, transcript);
  const cutShort = terminationRequested();
  const failures: string[] = [];

  try {
    // A fresh session, as /new gives the user: no earlier run's turns in the scenario's context.
    await deliverTurn(adapter, user.platformUserId, { send: "/new" });
    for (const [index, turn] of scenario.turns.entries()) {
      const before = transcript.getEvents().length;
      if (turn.outage) adapter.startOutage(turn.outage);
      await deliverTurnMessages(adapter, user.platformUserId, turn);
      let restartedAt: number | undefined;
      const { restartAfterSends } = turn;
      if (restartAfterSends !== undefined) {
        await withTimeout(
          transcript.until(
            (events) =>
              events.slice(before).filter((e) => e.type === "send").length >=
              restartAfterSends,
          ),
          RESTART_TRIGGER_TIMEOUT_MS,
          `the reply never sent ${restartAfterSends} messages to restart after`,
        );
        // As the bot process does on Ctrl-C: its follows stop where they are.
        await adapter.shutdown("restart");
        restartedAt = transcript.getEvents().length;
        adapter = await bootAdapter(platform, apiUrl, transcript);
      }
      await adapter.settleTurn();
      if (restartedAt !== undefined) {
        const resumed = restartResumedABubble(
          transcript.getEvents().slice(before),
          restartedAt - before,
        );
        if (resumed !== null) {
          failures.push(`turn ${index + 1} (${turnLabel(turn)}): ${resumed}`);
        }
      }
      // Settle BEFORE slicing: a late outbound delivery belongs to the turn
      // that caused it, and its assertions must be able to see it.
      await settle(
        turn.settleMs ?? settleMsOverride ?? scenario.settleMs ?? 0,
        cutShort,
      );
      const turnEvents = transcript.getEvents().slice(before);
      for (const assertion of turn.expect ?? []) {
        for (const failure of evaluateAssertion(turnEvents, assertion)) {
          failures.push(`turn ${index + 1} (${turnLabel(turn)}): ${failure}`);
        }
      }
    }
    // Leave nothing running or pending: a later run's bot would resume it and wait on it.
    await deliverTurn(adapter, user.platformUserId, { send: "/stop" });
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

/** A turn's messages: its single `send`, or its burst. */
function turnMessages(turn: ScenarioTurn): BurstMessage[] {
  if (turn.send !== undefined && turn.burst === undefined) {
    return [{ send: turn.send }];
  }
  if (turn.burst !== undefined && turn.send === undefined) {
    if (turn.burst.length === 0) {
      throw new Error("a scenario burst needs at least one message");
    }
    return turn.burst;
  }
  throw new Error("a scenario turn sets exactly one of `send` and `burst`");
}

function turnLabel(turn: ScenarioTurn): string {
  return turnMessages(turn)
    .map((message) => `"${message.send}"`)
    .join(" + ");
}

/**
 * Injects a turn's messages at their scripted gaps, each without waiting for
 * the reply to the one before, and resolves once every reply has been shown or
 * the conversation waits on an approval the user was asked.
 */
export async function deliverTurn(
  adapter: HarnessAdapter,
  platformUserId: string,
  turn: ScenarioTurn,
): Promise<void> {
  await deliverTurnMessages(adapter, platformUserId, turn);
  await adapter.settleTurn();
}

/** Injects a turn's messages at their scripted gaps and resolves once each is posted. */
async function deliverTurnMessages(
  adapter: HarnessAdapter,
  platformUserId: string,
  turn: ScenarioTurn,
): Promise<void> {
  const handled: Promise<void>[] = [];
  for (const message of turnMessages(turn)) {
    if (message.afterMs) {
      await new Promise((resolve) => setTimeout(resolve, message.afterMs));
    }
    handled.push(
      adapter.simulateMessage(platformUserId, message.send, {
        channelId: turn.channelId,
      }),
    );
  }
  await Promise.all(handled);
}

/**
 * The final text of everything still delivered, in the order each first appeared:
 * a bubble holds its last edit, and with `proactive` a
 * backend delivery and an attachment caption are entries of their own.
 */
function deliveredTexts(
  events: readonly TranscriptEvent[],
  proactive: boolean,
): string[] {
  const texts: (string | null)[] = [];
  const indexById = new Map<string, number>();
  for (const event of events) {
    if (event.type === "send" || event.type === "edit") {
      const index = indexById.get(event.messageId);
      if (index === undefined) {
        indexById.set(event.messageId, texts.length);
        texts.push(event.text);
      } else {
        texts[index] = event.text;
      }
    } else if (event.type === "delete") {
      const index = indexById.get(event.messageId);
      if (index !== undefined) texts[index] = null;
    } else if (
      proactive &&
      (event.type === "outbound-delivery" ||
        event.type === "outbound-attachment")
    ) {
      texts.push(event.text);
    }
  }
  return texts.filter((text) => text !== null);
}

/** 1-based positions of the inbound messages that received a reaction. */
function reactedPositions(events: readonly TranscriptEvent[]): number[] {
  const reacted = new Set(
    events.flatMap((e) => (e.type === "reaction" ? [e.targetMessageId] : [])),
  );
  const positions: number[] = [];
  let inboundCount = 0;
  for (const event of events) {
    if (event.type !== "inbound") continue;
    inboundCount += 1;
    if (reacted.has(event.messageId)) positions.push(inboundCount);
  }
  return positions;
}

/** Bubbles deleted, or edited to text shorter than they showed: what the user saw taken back. */
function takeBacks(events: readonly TranscriptEvent[]): string[] {
  const shown = new Map<string, string>();
  const found: string[] = [];
  for (const event of events) {
    if (event.type === "send") shown.set(event.messageId, event.text);
    if (event.type === "edit") {
      const before = shown.get(event.messageId);
      if (before !== undefined && event.text.length < before.length) {
        found.push(
          `${event.messageId} shrank from ${JSON.stringify(before)} to ${JSON.stringify(event.text)}`,
        );
      }
      shown.set(event.messageId, event.text);
    }
    if (event.type === "delete") {
      found.push(
        `${event.messageId} was deleted: ${JSON.stringify(shown.get(event.messageId))}`,
      );
    }
  }
  return found;
}

/** Each bubble's final text and the 1-based turn position of the inbound message it quotes, or null. */
function bubbleQuotes(
  events: readonly TranscriptEvent[],
): { text: string; quotes: number | null }[] {
  const inbound = events.flatMap((e) =>
    e.type === "inbound" ? [e.messageId] : [],
  );
  const bubbles = new Map<string, { text: string; quotes: number | null }>();
  for (const event of events) {
    if (event.type === "send") {
      const at =
        event.replyTo === undefined ? -1 : inbound.indexOf(event.replyTo);
      bubbles.set(event.messageId, {
        text: event.text,
        quotes: at < 0 ? null : at + 1,
      });
    } else if (event.type === "edit") {
      const bubble = bubbles.get(event.messageId);
      if (bubble) bubble.text = event.text;
    } else if (event.type === "delete") {
      bubbles.delete(event.messageId);
    }
  }
  return [...bubbles.values()];
}

/** All text-bearing events carry a `text` field; this narrows to it. */
function eventText(event: TranscriptEvent): string | null {
  return "text" in event && typeof event.text === "string" ? event.text : null;
}

/** The quotes, take-back and excluded-text checks of an assertion: what the user saw and how. */
function shownTextFailures(
  events: readonly TranscriptEvent[],
  assertion: ScenarioAssertion,
): string[] {
  const failures: string[] = [];
  if (assertion.quotes !== undefined) {
    const bubbles = bubbleQuotes(events);
    for (const [text, wanted] of Object.entries(assertion.quotes)) {
      const bubble = bubbles.find((b) => b.text.includes(text));
      if (!bubble) {
        failures.push(`no bubble reads "${text}" to check what it quotes`);
      } else if (bubble.quotes !== wanted) {
        failures.push(
          `the bubble "${text}" quotes inbound ${bubble.quotes}, expected ${wanted}`,
        );
      }
    }
  }
  if (assertion.noTakeBacks) {
    for (const takeBack of takeBacks(events)) {
      failures.push(`shown text was taken back: ${takeBack}`);
    }
  }
  const finalTexts = deliveredTexts(events, true);
  for (const banned of assertion.excludes ?? []) {
    const shown = finalTexts.find((text) => text.includes(banned));
    if (shown !== undefined) {
      failures.push(
        `delivered text contains "${banned}": ${JSON.stringify(shown)}`,
      );
    }
  }
  return failures;
}

/**
 * Why a restart turn tested nothing, or null when it did: the fresh bot must
 * finish in place a bubble the stopped one had opened. A reply that ended
 * before the restart leaves the scenario passing without exercising the resume.
 */
function restartResumedABubble(
  events: readonly TranscriptEvent[],
  restartedAt: number,
): string | null {
  const opened = new Set(
    events
      .slice(0, restartedAt)
      .flatMap((e) => (e.type === "send" ? [e.messageId] : [])),
  );
  const finishedInPlace = events
    .slice(restartedAt)
    .some((e) => e.type === "edit" && opened.has(e.messageId));
  return finishedInPlace
    ? null
    : "the restart hit no open bubble: nothing the stopped bot sent was finished in place after it (the bubble finished before the bot stopped)";
}

/**
 * Checks one assertion against a turn's events, returning a list of human
 * readable failure messages (empty when the assertion holds).
 */
export function evaluateAssertion(
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
      e.type === "send" ||
      e.type === "edit" ||
      e.type === "outbound-delivery" ||
      e.type === "outbound-attachment",
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
  const orderedChecks: [string, string[] | undefined, string[]][] = [
    ["delivered", assertion.delivered, deliveredTexts(events, true)],
    ["bubbles", assertion.bubbles, deliveredTexts(events, false)],
  ];
  for (const [name, wanted, actual] of orderedChecks) {
    if (wanted === undefined) continue;
    const matches =
      actual.length === wanted.length &&
      wanted.every((text, i) => actual[i].includes(text));
    if (!matches) {
      failures.push(
        `expected ${name} ${JSON.stringify(wanted)}, got ${JSON.stringify(actual)}`,
      );
    }
  }
  failures.push(...shownTextFailures(events, assertion));
  if (assertion.reactedTo !== undefined) {
    const actual = reactedPositions(events);
    const wanted = [...assertion.reactedTo].sort((a, b) => a - b);
    if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
      failures.push(
        `expected reactions on inbound ${JSON.stringify(wanted)}, got ${JSON.stringify(actual)}`,
      );
    }
  }
  return failures;
}
