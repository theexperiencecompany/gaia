/**
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║ CROSS-RUNTIME CONTRACT — MIRROR EVERY SHAPE CHANGE IN PYTHON           ║
 * ║                                                                        ║
 * ║ This file is ONE HALF of GAIA's wide-event shape. The other half is    ║
 * ║   libs/shared/py/wide_events.py                                        ║
 * ║ (`wide_task` / `log_context` / `log` / `WideEventFields`), used by the ║
 * ║ API, the worker and the voice agent. One LogQL query has to span both  ║
 * ║ surfaces, so the two MUST agree on key names and value types. Today's  ║
 * ║ shared contract:                                                       ║
 * ║                                                                        ║
 * ║   task        the boundary's unit-of-work name (NOT `operation` —      ║
 * ║               `operation` is the domain verb app code sets, on both    ║
 * ║               sides, and would clobber the boundary identity)          ║
 * ║   trace_id    16 lowercase hex chars                                   ║
 * ║   duration_ms number, milliseconds, 2 decimals                         ║
 * ║   outcome     "success" | "failed" | "cancelled"                       ║
 * ║   final_level loguru level name — "WARNING", never "WARN"              ║
 * ║   errors[] / warnings[] / audit[]                                      ║
 * ║               entries shaped {msg, ...fields}; a thrown value          ║
 * ║               contributes error_type=<name>, error=<message>. `error`  ║
 * ║               is a STRING on every surface — never a nested object.    ║
 * ║                                                                        ║
 * ║ If you are an agent editing ONLY this file, before you finish:         ║
 * ║  1. Open libs/shared/py/wide_events.py and make the matching change    ║
 * ║     (`_wide_event_boundary`, `WideEventLogger._append`,                ║
 * ║      `WideEventFields`).                                               ║
 * ║  2. Update scripts/ci/wide-event-conformance/contract.json, the single ║
 * ║     shared description both runtimes are checked against.              ║
 * ║  3. Run: python3 scripts/ci/wide-event-conformance/run.py              ║
 * ║     It emits real events from BOTH runtimes and diffs their shapes, so ║
 * ║     skipping step 1 or 2 is a red CI lane, not a silent drift.         ║
 * ║                                                                        ║
 * ║ The line envelope (time/level/env/service/commit/logger/message) is    ║
 * ║ NOT this file's job — `buildRecord` in ./logger.ts stamps it, mirroring║
 * ║ `_build_json_entry` in libs/shared/py/logging.py. Never re-add it here.║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Wide-event logging for the TypeScript bots — one context-rich structured
 * JSON event per handled interaction, mirroring the backend's
 * `libs/shared/py/wide_events.py` semantics:
 *
 * - `withWideEvent()`  → AsyncLocalStorage boundary; emits ONE canonical
 *   `bot_event` line on completion (success or throw)
 * - `wideLog.set()`    → merges structured fields into the active event
 * - `wideLog.setNs()`  → read-merges into a nested namespace dict
 * - `wideLog.warning()`→ real-time line + appended to the event's warnings[]
 * - `wideLog.error()`  → real-time line + appended to the event's errors[]
 * - `wideLog.audit()`  → real-time AUDIT line + appended to the event's audit[]
 *
 * Outside a boundary, `set`/`setNs` are discarded (isolation-safe, exactly
 * like the Python facade) while warning/error/audit still emit their
 * real-time lines. The trace_id generated per boundary is propagated to the
 * GAIA API via the `x-trace-id` request header (`GaiaClient.userHeaders`),
 * which the backend's LoggingMiddleware honours and echoes back — so a bot
 * event and the backend request it triggered share one trace_id.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import type { PlatformName } from "../types";
import {
  type BotLogFields,
  type BotLogLevel,
  emitBotLogLine,
  sanitizeErrorForLog,
} from "./logger";

/** The `message` value of every emitted wide-event line. */
export const WIDE_EVENT_MESSAGE = "bot_event";

/** One warnings[]/errors[]/audit[] entry: the message plus structured fields. */
export interface WideEventEntry {
  msg: string;
  [key: string]: unknown;
}

/**
 * Canonical wide-event field schema for the bots — the TS analogue of
 * `WideEventFields` in `libs/shared/py/wide_events.py`. Using consistent
 * names keeps LogQL queries uniform across every bot platform; the
 * observability scanner (`scripts/ci/checks.mjs evlog-map-bots`) parses this
 * interface live, so a new field is recognized the moment it lands here.
 */
export interface BotWideEventFields {
  /** Domain verb the handler is performing — the analogue of Python's
   *  top-level `operation`. NOT the boundary's name; that is `task`. */
  operation?: string;
  outcome?: string;
  platform?: string;
  component?: string;
  command?: string;
  user_hash?: string;
  channel_hash?: string;
  destination_hash?: string;
  message_length?: number;
  has_files?: boolean;
  has_attachment?: boolean;
  streaming_enabled?: boolean;
  ttfb_ms?: number;
  chunk_count?: number;
  response_length?: number;
  conversation_id?: string;
  media_kind?: string;
  is_voice_note?: boolean;
  envelope_id?: string;
  queue?: string;
  http_status?: number;
  event_type?: string;
  event_count?: number;
  delivered_count?: number;
  attachment_filename?: string;
  /** Exception class/name. Paired with `error` (its message) — never a nested
   *  object; see sanitizeErrorForLog in ./logger.ts. */
  error_type?: string;
  error?: string;
  // Process/adapter lifecycle.
  command_count?: number;
  server_port?: number;
  boot_stage?: string;
  trigger?: string;
  fault?: string;
  exit_code?: number;
  linked_count?: number;
  prewarmed_count?: number;
  // Internal wide-event metadata stamped by the boundary itself. `task` is the
  // unit-of-work name, matching `task` on Python's wide_task()/log_context()
  // events so `sum by (task)` spans the bots and the workers alike.
  task?: string;
  trace_id?: string;
  duration_ms?: number;
  final_level?: string;
  errors?: WideEventEntry[];
  warnings?: WideEventEntry[];
  audit?: WideEventEntry[];
}

/** Initial boundary context: platform is required so the emitted event lands under the right service. */
export type WideEventBoundaryFields = BotLogFields & {
  platform: PlatformName | "shared";
  component?: string;
};

const LEVEL_ORDER: Record<string, number> = {
  DEBUG: 0,
  INFO: 1,
  WARNING: 2,
  ERROR: 3,
};

interface WideEventState {
  task: string;
  platform: PlatformName | "shared";
  component: string;
  traceId: string;
  fields: Record<string, unknown>;
  errors: WideEventEntry[];
  warnings: WideEventEntry[];
  audit: WideEventEntry[];
  maxLevel: "INFO" | "WARNING" | "ERROR";
}

const storage = new AsyncLocalStorage<WideEventState>();

const DEFAULT_COMPONENT = "wide-events";

function generateTraceId(): string {
  return randomUUID().replaceAll("-", "").slice(0, 16);
}

// A namespace is a plain object literal. The prototype check is what keeps
// Date/Map/Set/RegExp/class instances out: `typeof` reports "object" for all of
// them, and spreading one keeps only its own enumerable properties — two Dates
// merge to `{}`, destroying the value instead of overwriting it. Python's half
// of this contract gets that for free (`isinstance(x, dict)` rejects a
// datetime), so without this the two runtimes disagree on the same input.
function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function mergeFields(
  target: Record<string, unknown>,
  fields: BotLogFields,
): void {
  for (const [key, value] of Object.entries(fields)) {
    if (value === undefined) continue;
    // Merge a namespace INTO what is already there rather than replacing it, so
    // every layer of a request accumulates onto one namespace instead of the
    // last writer silently winning. One level deep, object-into-object only —
    // a scalar still overwrites. Mirrors `set` in wide_events.py; the two log
    // shapes are one contract (wide-event-conformance CI lane).
    const existing = target[key];
    target[key] =
      isPlainObject(existing) && isPlainObject(value)
        ? { ...existing, ...value }
        : value;
  }
}

function bump(state: WideEventState, level: "WARNING" | "ERROR"): void {
  if (LEVEL_ORDER[level] > LEVEL_ORDER[state.maxLevel]) {
    state.maxLevel = level;
  }
}

/**
 * Emits the real-time line for a warning/error/audit call and, when a
 * boundary is active, appends the entry to the event's matching array.
 */
function record(
  level: BotLogLevel,
  category: "warnings" | "errors" | "audit",
  message: string,
  fields?: BotLogFields,
  error?: unknown,
): void {
  const state = storage.getStore();
  const platform = state?.platform ?? "shared";
  const component = state?.component ?? DEFAULT_COMPONENT;
  emitBotLogLine(level, platform, component, message, fields, error);
  if (!state) return;
  // Same precedence as buildRecord in ./logger.ts: the throwable's derived
  // error_type/error go in first, an explicit caller field wins over them.
  const entry: WideEventEntry = { msg: message };
  if (error !== undefined) mergeFields(entry, sanitizeErrorForLog(error));
  if (fields) mergeFields(entry, fields);
  state[category].push(entry);
  if (level === "warn") bump(state, "WARNING");
  if (level === "error") bump(state, "ERROR");
}

/**
 * The wide-event accumulator facade — the bots' equivalent of the Python
 * `log` object. All methods are safe to call outside a boundary.
 */
export const wideLog = {
  /** Merge structured context into the active wide event (no-op outside a boundary). */
  set(fields: BotLogFields): void {
    const state = storage.getStore();
    if (!state) return;
    mergeFields(state.fields, fields);
  },

  /**
   * Read-merge into a nested namespace dict on the event. Identical to
   * `set({ [namespace]: fields })` — kept because naming the namespace
   * explicitly reads better on a multi-step path. It delegates so the two can
   * never drift apart again.
   */
  setNs(namespace: string, fields: BotLogFields): void {
    this.set({ [namespace]: fields } as BotLogFields);
  },

  /** Real-time warn line + appended to the event's warnings[]; raises its final level. */
  warning(message: string, fields?: BotLogFields): void {
    record("warn", "warnings", message, fields);
  },

  /** Real-time error line + appended to the event's errors[]; raises its final level. */
  error(message: string, fields?: BotLogFields, error?: unknown): void {
    record("error", "errors", message, fields, error);
  },

  /**
   * Records an audit-trail entry for a sensitive operation (auth, tokens,
   * money). Emits a real-time AUDIT line and appends to the event's audit[]
   * without bumping severity — an audit entry is a record, not a problem.
   */
  audit(message: string, fields?: BotLogFields): void {
    record("audit", "audit", message, fields);
  },

  /** The active boundary's trace_id, or undefined outside a boundary. */
  getTraceId(): string | undefined {
    return storage.getStore()?.traceId;
  },
};

function emitWideEvent(state: WideEventState, durationMs: number): void {
  const event: BotLogFields = {
    // `task`, not `operation`: `operation` is the domain verb a handler sets
    // via wideLog.set() on both runtimes, so naming the boundary after it made
    // the two collide here and made `sum by (task)` blind to the bots.
    task: state.task,
    trace_id: state.traceId,
    ...state.fields,
    duration_ms: durationMs,
    final_level: state.maxLevel,
  };
  if (state.errors.length > 0) event.errors = state.errors;
  if (state.warnings.length > 0) event.warnings = state.warnings;
  if (state.audit.length > 0) event.audit = state.audit;
  const level: BotLogLevel =
    state.maxLevel === "ERROR"
      ? "error"
      : state.maxLevel === "WARNING"
        ? "warn"
        : "info";
  emitBotLogLine(
    level,
    state.platform,
    state.component,
    WIDE_EVENT_MESSAGE,
    event,
  );
}

/**
 * Binds a fresh wide event for `fn` and flushes ONE canonical `bot_event`
 * JSON line when it completes — the bots' `wide_task()`. Every
 * `wideLog.set()` inside `fn` (however deep in the async call tree) lands on
 * this event. On throw, the error is appended to errors[], `outcome` is
 * "failed", and the error is re-raised after the event is emitted.
 *
 * `task` names the unit of work ("command", "chat", "webhook") and is emitted
 * under that key, matching `wide_task("<name>")` in
 * libs/shared/py/wide_events.py.
 */
export async function withWideEvent<T>(
  task: string,
  fields: WideEventBoundaryFields,
  fn: () => Promise<T>,
): Promise<T> {
  const { platform, component, ...context } = fields;
  const state: WideEventState = {
    task,
    platform,
    component: typeof component === "string" ? component : DEFAULT_COMPONENT,
    traceId: generateTraceId(),
    fields: {},
    errors: [],
    warnings: [],
    audit: [],
    maxLevel: "INFO",
  };
  mergeFields(state.fields, context);
  const start = performance.now();
  return storage.run(state, async () => {
    try {
      const result = await fn();
      state.fields.outcome = "success";
      return result;
    } catch (error) {
      record("error", "errors", "task failed", undefined, error);
      state.fields.outcome = "failed";
      throw error;
    } finally {
      emitWideEvent(state, Math.round((performance.now() - start) * 100) / 100);
    }
  });
}
