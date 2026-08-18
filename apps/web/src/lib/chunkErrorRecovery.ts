"use client";

import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

/**
 * Recovery for stale-asset `ChunkLoadError`s.
 *
 * Every deploy emits `/_next/static/chunks/*` assets under content-hashed
 * filenames. A browser holding an already-loaded (or CDN-cached) document from
 * a previous deploy still references the old filenames; once those assets are
 * evicted from the CDN, the next lazy chunk fetch — during a route transition,
 * hydration, or a `next/dynamic` import — 404s and Turbopack's runtime throws a
 * `ChunkLoadError`, breaking the route. These surface as *unhandled* rejections
 * (Turbopack rejects the chunk-load promise and nothing awaits it), so they
 * never reach a React error boundary.
 *
 * Recovery is a single reload: a fresh document references current chunk
 * filenames. The reload is guarded by a short time window so a chunk that is
 * genuinely unrecoverable (still missing right after a fresh load) surfaces as
 * a retryable error instead of an infinite reload loop.
 */

// sessionStorage key holding the epoch-ms of the last recovery reload. Scoped
// to the tab so the guard survives the reload without leaking across tabs.
const RECOVERY_TIMESTAMP_KEY = "gaia:chunk-recovery-at";

// If a chunk error recurs within this window of a recovery reload, the reload
// did not fix it — stop reloading and let the error surface as retryable.
const RECOVERY_WINDOW_MS = 10_000;

// Turbopack throws with `name === "ChunkLoadError"`; the message reads
// "Failed to load chunk /_next/static/chunks/<hash>.js from module <id>". The
// message regex is a fallback for cases where the error `name` was lost while
// the rejection crossed an async boundary.
const CHUNK_ERROR_NAME = "ChunkLoadError";
const CHUNK_ERROR_MESSAGE =
  /Failed to load chunk|Loading chunk [\w-]+ failed|error loading dynamically imported module|Failed to fetch dynamically imported module/i;

export function isChunkLoadError(error: unknown): boolean {
  if (error instanceof Error) {
    return (
      error.name === CHUNK_ERROR_NAME || CHUNK_ERROR_MESSAGE.test(error.message)
    );
  }
  if (typeof error === "string") {
    return CHUNK_ERROR_MESSAGE.test(error);
  }
  return false;
}

function readLastRecoveryAt(): number | null {
  try {
    const raw = sessionStorage.getItem(RECOVERY_TIMESTAMP_KEY);
    if (raw === null) return null;
    const value = Number.parseInt(raw, 10);
    return Number.isNaN(value) ? null : value;
  } catch {
    // sessionStorage can be unavailable (sandboxed iframe, hardened privacy
    // mode). Losing the guard is acceptable — treat it as "no prior attempt".
    return null;
  }
}

function markRecoveryAttempt(now: number): void {
  try {
    sessionStorage.setItem(RECOVERY_TIMESTAMP_KEY, String(now));
  } catch {
    // Storage unavailable — the reload still runs; only the loop guard is lost.
  }
}

export type ChunkRecoveryResult = "reloading" | "terminal" | "ignored";

/**
 * Attempt to recover from a `ChunkLoadError`.
 *
 * @returns
 * - `"reloading"` — a recovery reload was triggered; the page is navigating
 *   away, so callers should stop rendering (no error UI).
 * - `"terminal"`  — a reload was already attempted within the recovery window
 *   and the chunk is still missing; callers should show a retryable error.
 * - `"ignored"`   — not a chunk error (or no `window`); handle it normally.
 */
export function recoverFromChunkError(error: unknown): ChunkRecoveryResult {
  if (typeof window === "undefined" || !isChunkLoadError(error)) {
    return "ignored";
  }

  const now = Date.now();
  const lastAttempt = readLastRecoveryAt();
  const alreadyReloaded =
    lastAttempt !== null && now - lastAttempt < RECOVERY_WINDOW_MS;

  if (alreadyReloaded) {
    trackEvent(ANALYTICS_EVENTS.ERROR_OCCURRED, {
      error_type: "chunk_load",
      recovery_action: "terminal",
    });
    return "terminal";
  }

  markRecoveryAttempt(now);
  // Best-effort: PostHog flushes queued events via `sendBeacon` on unload, so
  // this reload signal survives the reload when PostHog is already initialized.
  trackEvent(ANALYTICS_EVENTS.API_CHUNK_RECOVERED, {
    error_type: "chunk_load",
    recovery_action: "reload",
  });
  window.location.reload();
  return "reloading";
}

/**
 * Register global listeners that recover from *unhandled* `ChunkLoadError`s —
 * the async chunk-fetch rejections that bypass React error boundaries. Returns
 * a cleanup function that removes the listeners.
 */
export function registerGlobalChunkErrorRecovery(): () => void {
  const onError = (event: ErrorEvent): void => {
    // `event.error` is undefined for opaque cross-origin script errors; the
    // message is the only signal there, so fall back to it.
    if (recoverFromChunkError(event.error ?? event.message) === "reloading") {
      event.preventDefault();
    }
  };
  const onRejection = (event: PromiseRejectionEvent): void => {
    if (recoverFromChunkError(event.reason) === "reloading") {
      event.preventDefault();
    }
  };

  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
