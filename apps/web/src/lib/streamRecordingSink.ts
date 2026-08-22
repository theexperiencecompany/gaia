/**
 * Dev-only disk sink for `streamLogger` entries.
 *
 * The ring buffer in `streamLogger` only lives inside the tab, so an agent
 * debugging a chat turn can't see what the frontend actually received. This
 * ships every entry to a dev-only Next route handler that appends it to a
 * newline-delimited JSON file under `.agents/recording/stream/`, which an agent
 * can grep without a browser.
 *
 * No-op in production builds — `process.env.NODE_ENV` is inlined at build time,
 * so the whole module dead-code-eliminates.
 */

import type { StreamLogEntry } from "./streamLogger";

const ENDPOINT = "/api/dev/stream-recording";
const FLUSH_INTERVAL_MS = 750;

const isDev = process.env.NODE_ENV !== "production";

/** One recording file per page load. Turns inside it are separated by their
 *  `turn:start` / `turn:end` lifecycle entries and the `seq` ordering. */
let recordingId: string | null = null;
let queue: StreamLogEntry[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let unloadHookInstalled = false;
/** Serializes POSTs. Two in-flight requests can be appended in either order,
 *  which would scramble the recording — the log's whole value is that its line
 *  order is the order the browser saw. */
let inFlight: Promise<void> = Promise.resolve();

const getRecordingId = (): string => {
  if (recordingId === null) {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    // crypto over Math.random: same job (keep two recordings started in the same
    // second apart) without shipping a pseudorandom generator into the bundle.
    recordingId = `${stamp}-${crypto.randomUUID().slice(0, 6)}`;
  }
  return recordingId;
};

const serialize = (entries: StreamLogEntry[]): string =>
  JSON.stringify({ recordingId: getRecordingId(), entries });

const flush = (): void => {
  timer = null;
  if (queue.length === 0) return;
  const body = serialize(queue);
  queue = [];

  // Deliberately not `apiService`: that targets the FastAPI backend base URL and
  // layers auth headers, toasts and analytics on top. This is a same-origin,
  // dev-only Next route handler that must stay invisible to the user.
  inFlight = inFlight.then(() =>
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    })
      .then((response) => {
        if (!response.ok) {
          console.error(
            `[streamRecording] sink rejected ${response.status} — entries dropped`,
          );
        }
      })
      .catch((error: unknown) => {
        console.error("[streamRecording] sink unreachable:", error);
      }),
  );
};

const flushOnUnload = (): void => {
  if (queue.length === 0) return;
  const body = serialize(queue);
  queue = [];
  navigator.sendBeacon(
    ENDPOINT,
    new Blob([body], { type: "application/json" }),
  );
};

/** Queue one log entry for the on-disk recording. Batched so a token-by-token
 *  stream doesn't fire one request per frame. */
export const shipStreamLogEntry = (entry: StreamLogEntry): void => {
  if (!isDev || typeof window === "undefined") return;

  if (!unloadHookInstalled) {
    unloadHookInstalled = true;
    window.addEventListener("pagehide", flushOnUnload);
  }

  queue.push(entry);
  if (timer === null) {
    timer = setTimeout(flush, FLUSH_INTERVAL_MS);
  }
};
