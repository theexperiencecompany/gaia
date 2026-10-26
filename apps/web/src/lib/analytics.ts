"use client";

import type {
  EventProperties,
  WebEventName,
} from "@gaia/shared/analytics/events";
import type { UserId } from "@gaia/shared/analytics/identity";
import type { PostHog } from "posthog-js";

import { registerPostHogSessionId } from "@/lib/analytics-headers";

/**
 * Which surface put the paid-only wall on screen: the `source` property of
 * `paywall:modal_viewed`. Every `openModal` call must name one; add a member
 * to the catalog's literal when a new surface starts raising the wall.
 */
export type PaywallSource = EventProperties["paywall:modal_viewed"]["source"];

interface UserProperties {
  email?: string;
  name?: string;
  timezone?: string;
  plan?: string;
  created_at?: string;
  profession?: string;
  onboarding_completed?: boolean;
  first_message_sent?: boolean;
}

/**
 * The SDK is imported and initialised at browser idle (`instrumentation-client.ts`)
 * and handed over through `connectPostHog`; it is never imported here, so it stays
 * out of every page's eager bundle. A capture before init would be *dropped* —
 * `onboarding:started` on mount missed the head of the funnel this way for quick users.
 *
 * Calls made before that are buffered here and replayed in order by
 * `flushPendingAnalytics`; capped, since no project token (local dev) means the queue never flushes and would grow for the tab's life.
 */
type PendingCall =
  | { kind: "identify"; userId: string; properties: Record<string, unknown> }
  | { kind: "capture"; event: string; properties: Record<string, unknown> }
  | { kind: "person"; properties: UserProperties }
  | { kind: "reset" };

/** The SDK surface this module drives. */
type PostHogClient = Pick<
  PostHog,
  | "__loaded"
  | "identify"
  | "capture"
  | "captureException"
  | "setPersonProperties"
  | "reset"
  | "_isIdentified"
  | "get_distinct_id"
  | "get_session_id"
>;

const MAX_PENDING_CALLS = 50;
const pendingCalls: PendingCall[] = [];
let client: PostHogClient | null = null;

function readyClient(): PostHogClient | null {
  return client?.__loaded ? client : null;
}

function isIdentityChange(call: PendingCall): boolean {
  return call.kind === "identify" || call.kind === "reset";
}

/** Past the cap only events are dropped: a lost identify or reset misattributes everything after it. */
function enqueue(call: PendingCall): void {
  if (pendingCalls.length >= MAX_PENDING_CALLS && !isIdentityChange(call)) {
    return;
  }
  pendingCalls.push(call);
}

function send(posthog: PostHogClient, call: PendingCall): void {
  switch (call.kind) {
    case "identify":
      posthog.identify(call.userId, call.properties);
      break;
    case "capture":
      posthog.capture(call.event, call.properties);
      break;
    case "person":
      posthog.setPersonProperties(call.properties);
      break;
    case "reset":
      // An anonymous id carries pre-signup history; resetting it would orphan that.
      if (posthog._isIdentified()) posthog.reset();
      break;
  }
}

function dispatch(call: PendingCall): void {
  const posthog = readyClient();
  if (!posthog) {
    enqueue(call);
    return;
  }
  send(posthog, call);
}

/**
 * API requests carry the session id so server events join this browser's
 * session and replay. The header is built in `@/lib/analytics-headers`, which
 * server code can call; this client module supplies the live id.
 */
registerPostHogSessionId(() => readyClient()?.get_session_id());

const EMAIL_SHAPED = /^[^@\s]+@[^@\s]+$/;

/**
 * Drop a distinct_id persisted from before #1007, when the web identified by email.
 *
 * Call after init and before the queue replays, so a queued identify links the
 * fresh anonymous id to the Mongo id. Afterwards the id is a uuid, so it runs once.
 */
export function resetLegacyEmailIdentity(): void {
  const posthog = readyClient();
  if (!posthog) return;
  if (EMAIL_SHAPED.test(posthog.get_distinct_id())) posthog.reset();
}

/** Replays everything captured before `posthog.init` finished, in order. */
export function flushPendingAnalytics(): void {
  const posthog = readyClient();
  if (!posthog) return;
  const queued = pendingCalls.splice(0, pendingCalls.length);
  for (const call of queued) send(posthog, call);
}

/** Hand over the initialised SDK, then drop a legacy identity and replay the queue. */
export function connectPostHog(posthog: PostHogClient): void {
  client = posthog;
  resetLegacyEmailIdentity();
  flushPendingAnalytics();
}

/**
 * Identify a user in PostHog.
 * Call this when a user logs in or signs up.
 */
export function identifyUser(
  userId: UserId,
  properties?: UserProperties,
): void {
  dispatch({
    kind: "identify",
    userId,
    properties: {
      ...properties,
      $set_once: {
        first_seen: new Date().toISOString(),
      },
    },
  });
}

/**
 * End a signed-in identity: on logout, or a 401. An anonymous identity is kept.
 * Queued like identify, since posthog.reset() before init is a silent no-op.
 */
export function resetUser(): void {
  dispatch({ kind: "reset" });
}

/** Track a web-owned catalog event; server-owned events do not compile here. */
export function track<E extends WebEventName>(
  event: E,
  properties: EventProperties[E],
): void {
  dispatch({
    kind: "capture",
    event,
    // Stamped at call time, not at flush time: a buffered event must keep the
    // moment it actually happened.
    properties: { ...properties, timestamp: new Date().toISOString() },
  });
}

/**
 * Set user properties without tracking an event.
 */
export function setUserProperties(properties: UserProperties): void {
  dispatch({ kind: "person", properties });
}

/** Report an exception to PostHog error tracking; dropped before init, like the SDK's own. */
export function captureException(error: Error): void {
  readyClient()?.captureException(error);
}
