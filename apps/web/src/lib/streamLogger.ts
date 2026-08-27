/**
 * Dev-only structured stream logger.
 *
 * Records every streaming-related event (SSE frames, WebSocket dispatches,
 * accumulator applications, store writes, DB writes, render outcomes, lifecycle
 * transitions) into a ring buffer exposed as `window.__STREAM_LOG__`, mirrored
 * to the console. This is the observability backbone for debugging streaming and
 * for the Chrome DevTools verification harness (`window.__STREAM_LOG_DUMP__()`).
 *
 * Every entry is also shipped to disk as NDJSON (see `streamRecordingSink`) so a
 * coding agent can read what the browser received without a browser.
 *
 * Every function is a no-op in production builds.
 */

import { shipStreamLogEntry } from "./streamRecordingSink";

export type StreamLogLayer =
  | "sse"
  | "ws"
  | "accumulator"
  | "store"
  | "db"
  | "render"
  | "lifecycle";

export interface StreamLogEntry {
  seq: number;
  ts: string;
  /** Milliseconds since the most recent stream start (`*:start` lifecycle
   *  entry), so a reader can see the shape of a turn without parsing `ts`. */
  dtMs: number;
  layer: StreamLogLayer;
  event: string;
  turnKey?: string;
  conversationId?: string | null;
  detail?: unknown;
}

const RING_BUFFER_CAP = 2000;

const isDev = process.env.NODE_ENV !== "production";

interface StreamLogWindow extends Window {
  __STREAM_LOG__?: StreamLogEntry[];
  __STREAM_LOG_DUMP__?: () => string;
}

let seq = 0;
let streamStartedAt = Date.now();

const getBuffer = (): StreamLogEntry[] | null => {
  if (!isDev || typeof window === "undefined") return null;
  const w = window as StreamLogWindow;
  if (!w.__STREAM_LOG__) {
    w.__STREAM_LOG__ = [];
    w.__STREAM_LOG_DUMP__ = () => JSON.stringify(w.__STREAM_LOG__ ?? []);
  }
  return w.__STREAM_LOG__;
};

export const streamLog = (
  layer: StreamLogLayer,
  event: string,
  context?: {
    turnKey?: string;
    conversationId?: string | null;
    detail?: unknown;
  },
): void => {
  const buffer = getBuffer();
  if (!buffer) return;

  if (layer === "lifecycle" && event.endsWith(":start")) {
    streamStartedAt = Date.now();
  }

  const entry: StreamLogEntry = {
    seq: ++seq,
    ts: new Date().toISOString(),
    dtMs: Date.now() - streamStartedAt,
    layer,
    event,
    turnKey: context?.turnKey,
    conversationId: context?.conversationId,
    detail: context?.detail,
  };

  buffer.push(entry);
  shipStreamLogEntry(entry);
  if (buffer.length > RING_BUFFER_CAP) {
    buffer.splice(0, buffer.length - RING_BUFFER_CAP);
  }

  console.debug(
    `[stream:${layer}] #${entry.seq} ${event}`,
    context?.conversationId ?? "",
    context?.detail ?? "",
  );
};

/** Loud dev-surface for stream contract violations (malformed frames etc.). */
export const streamLogError = (
  layer: StreamLogLayer,
  event: string,
  context?: {
    turnKey?: string;
    conversationId?: string | null;
    detail?: unknown;
  },
): void => {
  if (!isDev) return;
  streamLog(layer, `ERROR:${event}`, context);
  console.error(`[stream:${layer}] ${event}`, context?.detail ?? "");
};
