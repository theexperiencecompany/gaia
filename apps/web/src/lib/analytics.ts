"use client";

import type {
  EventProperties,
  WebEventName,
} from "@gaia/shared/analytics/events";
import type { UserId } from "@gaia/shared/analytics/identity";
import posthog from "posthog-js";

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
 * `posthog.init` is deferred to browser idle (`instrumentation-client.ts`), and
 * `posthog.capture` before init is silently *dropped* — `onboarding:started`
 * on mount missed the head of the funnel this way for quick users.
 *
 * Calls made before init are buffered here and replayed in order by
 * `flushPendingAnalytics`; capped, since no project token (local dev) means the queue never flushes and would grow for the tab's life.
 */
type PendingCall =
  | { kind: "identify"; userId: string; properties: Record<string, unknown> }
  | { kind: "capture"; event: string; properties: Record<string, unknown> }
  | { kind: "person"; properties: UserProperties }
  | { kind: "reset" };

const MAX_PENDING_CALLS = 50;
const pendingCalls: PendingCall[] = [];

function isPostHogReady(): boolean {
  return posthog.__loaded;
}

function enqueue(call: PendingCall): void {
  if (pendingCalls.length >= MAX_PENDING_CALLS) return;
  pendingCalls.push(call);
}

function send(call: PendingCall): void {
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
      posthog.reset();
      break;
  }
}

function dispatch(call: PendingCall): void {
  if (!isPostHogReady()) {
    enqueue(call);
    return;
  }
  send(call);
}

/** Sent on every API request so server events join this browser's session and replay. */
const POSTHOG_SESSION_HEADER = "X-PostHog-Session-Id";

/** The analytics headers for an API request; empty until PostHog has a session. */
export function analyticsRequestHeaders(): Record<string, string> {
  if (!isPostHogReady()) return {};
  return { [POSTHOG_SESSION_HEADER]: posthog.get_session_id() };
}

const EMAIL_SHAPED = /^[^@\s]+@[^@\s]+$/;

/**
 * Drop a distinct_id persisted from before #1007, when the web identified by email.
 *
 * Call after init and before the queue replays, so a queued identify links the
 * fresh anonymous id to the Mongo id. Afterwards the id is a uuid, so it runs once.
 */
export function resetLegacyEmailIdentity(): void {
  if (!isPostHogReady()) return;
  if (EMAIL_SHAPED.test(posthog.get_distinct_id())) posthog.reset();
}

/** Replays everything captured before `posthog.init` finished, in order. */
export function flushPendingAnalytics(): void {
  if (!isPostHogReady()) return;
  const queued = pendingCalls.splice(0, pendingCalls.length);
  for (const call of queued) send(call);
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
 * Reset user identity: on logout, or a 401 that ends a signed-in session.
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
