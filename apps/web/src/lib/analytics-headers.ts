/**
 * The analytics headers an API request carries, in a plain module (no
 * `"use client"`) so both trees can call it.
 *
 * `lib/api/client.ts` is imported by server code as well as the browser, and a
 * function exported from a `"use client"` module is only a client reference on
 * the server — calling it throws ("Attempted to call analyticsRequestHeaders()
 * from the server"), which broke static generation. posthog-js must never reach
 * the server graph, so the browser analytics module registers how to read its
 * session id here instead.
 */

/** Sent on every API request so server events join this browser's session and replay. */
const POSTHOG_SESSION_HEADER = "X-PostHog-Session-Id";

/** The current PostHog session id, or undefined while posthog is not loaded. */
type SessionIdReader = () => string | undefined;

let readSessionId: SessionIdReader | null = null;

/** Called by `@/lib/analytics`, the only module that imports posthog-js. */
export function registerPostHogSessionId(reader: SessionIdReader): void {
  readSessionId = reader;
}

/** The analytics headers for an API request; empty on the server and until PostHog has a session. */
export function analyticsRequestHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const sessionId = readSessionId?.();
  return sessionId ? { [POSTHOG_SESSION_HEADER]: sessionId } : {};
}
