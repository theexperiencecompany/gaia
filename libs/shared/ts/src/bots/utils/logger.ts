/**
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║ CROSS-RUNTIME CONTRACT — MIRROR EVERY SHAPE CHANGE IN PYTHON           ║
 * ║                                                                        ║
 * ║ This file is ONE HALF of GAIA's log envelope. The other half is        ║
 * ║   libs/shared/py/logging.py  (function `_build_json_entry`)            ║
 * ║ and it MUST emit the same key names, the same value types and the      ║
 * ║ same timestamp format, because one LogQL query (`| json | ...`) has    ║
 * ║ to span the TypeScript bots and the Python services at once. A field   ║
 * ║ that exists here and not there — or exists on both with a different    ║
 * ║ type — silently breaks every dashboard that joins the two surfaces.    ║
 * ║                                                                        ║
 * ║ If you are an agent editing ONLY this file, before you finish:         ║
 * ║  1. Open libs/shared/py/logging.py and make the matching change in     ║
 * ║     `_build_json_entry` / `_CORE_KEYS` / `_COLLIDING_KEY_PREFIX` /     ║
 * ║     `env_context`.                                                     ║
 * ║  2. Update the shared contract both sides are checked against:         ║
 * ║     scripts/ci/wide-event-conformance/contract.json                    ║
 * ║  3. Run the conformance check — it emits real lines from BOTH          ║
 * ║     runtimes and diffs their shapes:                                   ║
 * ║       python3 scripts/ci/wide-event-conformance/run.py                 ║
 * ║     It fails if the two runtimes disagree, so skipping step 1 or 2 is  ║
 * ║     a red CI lane, not a silent drift.                                 ║
 * ║                                                                        ║
 * ║ Envelope keys stamped on EVERY line by both runtimes:                  ║
 * ║   time, level, env, service, commit, logger, message                   ║
 * ║ TS-only envelope: platform, component (Python carries both as          ║
 * ║   ordinary optional wide-event fields with the same names and types)   ║
 * ║ Python-only provenance: module, line, worker (loguru record data with  ║
 * ║   no TS equivalent — declared as Python-only in the contract, do NOT   ║
 * ║   invent stack-parsed stand-ins for them here)                         ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 */
import { createHash, createHmac } from "node:crypto";
import type { PlatformName } from "../types";
import { appendStructuredLogLine } from "./log-file-sink";

/** `audit` mirrors the backend's custom AUDIT loguru level (between info and warn). */
export type BotLogLevel = "debug" | "info" | "warn" | "error" | "audit";

/**
 * The `level` value written to the log line. These are loguru's level names,
 * not the TS method names — the Python services emit "WARNING" and Promtail
 * promotes `level` to an indexed Loki label, so `{level="WARNING"}` has to
 * match a bot line and an API line alike.
 */
const LOG_LEVEL_NAMES: Record<BotLogLevel, string> = {
  debug: "DEBUG",
  info: "INFO",
  warn: "WARNING",
  error: "ERROR",
  audit: "AUDIT",
};

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type BotLogFields = Record<string, unknown>;

export interface BotLogger {
  debug: (event: string, fields?: BotLogFields) => void;
  info: (event: string, fields?: BotLogFields) => void;
  warn: (event: string, fields?: BotLogFields) => void;
  error: (event: string, fields?: BotLogFields, error?: unknown) => void;
}

/**
 * Loki drops any line over its `max_line_size` (256 KB by default), silently —
 * the log is simply never queryable. Cap below it, matching
 * MAX_JSON_LINE_BYTES / _truncated_entry in `libs/shared/py/logging.py` so an
 * oversized line degrades to a minimal, still-ingestible record on every GAIA
 * surface instead of vanishing on one of them.
 */
const MAX_JSON_LINE_BYTES = 200_000;
const TRUNCATED_MESSAGE_MAX_CHARS = 10_000;

/**
 * Envelope keys `buildRecord` always sets — kept when a line has to be shrunk.
 * Same order as `_CORE_KEY_ORDER` in libs/shared/py/logging.py, minus the
 * loguru-only provenance (module/line/worker) that has no TS equivalent.
 */
const ENVELOPE_KEYS = [
  "time",
  "level",
  "env",
  "service",
  "commit",
  "logger",
  "platform",
  "component",
  "message",
] as const;

/**
 * A caller field named like an envelope key would corrupt the line's identity,
 * so it is re-emitted under {@link COLLIDING_KEY_PREFIX} instead. `error` is
 * deliberately NOT here: an exception is described by the flat scalars
 * `error_type` + `error` (see {@link sanitizeErrorForLog}), exactly as in
 * Python, so `error` is ordinary payload on both surfaces.
 */
const RESERVED_LOG_KEYS: ReadonlySet<string> = new Set(ENVELOPE_KEYS);

/**
 * Prefix for a caller field that collided with an envelope key. Must equal
 * `_COLLIDING_KEY_PREFIX` in libs/shared/py/logging.py — `ctx_` is the spelling
 * the wide-events lint quotes to app authors (tools/lints/README.md), so a
 * second prefix would mean two things to grep for after the same mistake.
 */
const COLLIDING_KEY_PREFIX = "ctx_";

/**
 * The `service` value stamped on every log line. Must match the Promtail label
 * for the container the line is emitted from (the Docker Compose service names:
 * `discord-bot`, `slack-bot`, `telegram-bot`, `whatsapp-bot` — see
 * infra/docker/observability/promtail-config.yaml), so
 * `{service="discord-bot"} | json | service="discord-bot"` agrees with itself.
 * Loggers created with the "shared" platform (module-scope loggers in shared
 * code) resolve via the container's `BOT_NAME` env (set in apps/bots/Dockerfile),
 * falling back to "gaia-bots" outside a bot container.
 */
function resolveServiceName(platform: PlatformName | "shared"): string {
  if (platform !== "shared") return `${platform}-bot`;
  const botName = process.env.BOT_NAME;
  return botName ? `${botName}-bot` : "gaia-bots";
}

/**
 * Deployment environment, resolved exactly as `env_context()` does in
 * libs/shared/py/logging.py: `ENV` (GAIA's own variable, set by
 * apps/api/Dockerfile) → `NODE_ENV` (the Node spelling, set by
 * apps/bots/Dockerfile) → "development". Reading only `NODE_ENV` made `env` a
 * build-mode flag on one surface and a deployment label on the other, so
 * `| json | env="production"` meant two different things.
 */
function resolveEnv(): string {
  return process.env.ENV || process.env.NODE_ENV || "development";
}

/** Short commit sha stamped on every line — parity with Python's env_context(). */
function resolveCommit(): string {
  return (
    process.env.GIT_COMMIT_SHA ||
    process.env.COMMIT_SHA ||
    "local"
  ).slice(0, 8);
}

export function hashLogIdentifier(
  value: string | number | undefined | null,
): string | undefined {
  if (value === undefined || value === null) return undefined;

  const normalized = String(value);
  const secret =
    process.env.BOT_LOG_HASH_SECRET ?? process.env.GAIA_BOT_API_KEY;

  const digest = secret
    ? createHmac("sha256", secret).update(normalized).digest("hex")
    : createHash("sha256").update(normalized).digest("hex");

  return `h_${digest.slice(0, 16)}`;
}

/**
 * Extracts the HTTP status from an Axios-style error (`error.response.status`),
 * or `undefined` if absent. Centralizes the repeated `unknown`-cast that every
 * call site (API client, streaming, media, formatters) was duplicating.
 */
export function getHttpStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } } | null)?.response?.status;
}

/**
 * Describe a thrown value with the two flat scalars every GAIA surface uses:
 * `error_type` (the exception's class/name) and `error` (its message).
 *
 * These names are the contract, not a preference. Python's `log.error(...,
 * error=str(exc), error_type=type(exc).__name__)` is the vocabulary of ~900 call
 * sites, the wide-events lint and the observability scanner. Nesting the pair
 * under a single `error: {...}` object — as this used to — put a string on one
 * surface and an object on the other under the SAME key, which is the one shape
 * `| json` cannot cope with: the label is dropped and the line silently falls
 * out of every error dashboard.
 */
export function sanitizeErrorForLog(error: unknown): BotLogFields {
  if (error instanceof Error) {
    return {
      error_type: error.name,
      error: error.message,
    };
  }

  return {
    error_type: "Unknown",
    error: typeof error === "string" ? error : "Unknown non-Error thrown",
  };
}

function toJsonValue(value: unknown, depth = 0): JsonValue {
  if (depth > 3) return "[truncated]";
  if (value === null) return null;

  const valueType = typeof value;
  if (
    valueType === "string" ||
    valueType === "number" ||
    valueType === "boolean"
  ) {
    return value as string | number | boolean;
  }

  if (valueType === "bigint") return String(value);
  if (valueType === "undefined") return "[undefined]";
  if (valueType === "function") return "[function]";

  if (value instanceof Error) {
    return {
      name: value.name,
      message: value.message,
      stack: value.stack ?? "",
    };
  }

  if (Array.isArray(value)) {
    return value.slice(0, 25).map((entry) => toJsonValue(entry, depth + 1));
  }

  if (valueType === "object") {
    const out: Record<string, JsonValue> = {};
    for (const [key, entry] of Object.entries(
      value as Record<string, unknown>,
    )) {
      if (entry === undefined) continue;
      out[key] = toJsonValue(entry, depth + 1);
    }
    return out;
  }

  return String(value);
}

function write(level: BotLogLevel, line: string): void {
  if (level === "debug") {
    console.debug(line);
    return;
  }
  if (level === "info" || level === "audit") {
    console.log(line);
    return;
  }
  if (level === "warn") {
    console.warn(line);
    return;
  }
  console.error(line);
}

/**
 * Builds the canonical envelope. The key names are deliberately identical to
 * the ones `_build_json_entry` emits in `libs/shared/py/logging.py` — `time`,
 * `level`, `env`, `service`, `commit`, `logger`, `message`, plus the wide-event
 * fields (`task`, `trace_id`, `duration_ms`, `outcome`, `errors`, `warnings`,
 * `audit`) — so a single LogQL query spans the Python services and the bots.
 * The event name lands under `message`, not `event`, for exactly that reason.
 */
function buildRecord(
  time: string,
  level: BotLogLevel,
  platform: PlatformName | "shared",
  component: string,
  event: string,
  fields?: BotLogFields,
  error?: unknown,
): Record<string, JsonValue> {
  const record: Record<string, JsonValue> = {
    time,
    level: LOG_LEVEL_NAMES[level],
    env: resolveEnv(),
    service: resolveServiceName(platform),
    commit: resolveCommit(),
    // Promtail extracts `logger` into the logger_name label (see
    // infra/docker/observability/promtail-config.yaml pipeline_stages).
    logger: component,
    platform,
    component,
    message: event,
  };

  // Derived-from-the-throwable first, caller fields second: an explicit
  // `error_type` passed by the call site describes the failure better than the
  // JS `Error.name` it would otherwise be overwritten by, and Python — where
  // every one of these fields is explicit — has no derived value to lose.
  if (error !== undefined) {
    for (const [key, value] of Object.entries(sanitizeErrorForLog(error))) {
      record[key] = toJsonValue(value);
    }
  }

  if (fields) {
    for (const [key, value] of Object.entries(fields)) {
      if (value === undefined) continue;
      const safeKey = RESERVED_LOG_KEYS.has(key)
        ? `${COLLIDING_KEY_PREFIX}${key}`
        : key;
      record[safeKey] = toJsonValue(value);
    }
  }

  return record;
}

/**
 * Replaces an over-cap line with a minimal record carrying the envelope, a
 * truncated message and `trace_id`, plus `line_truncated`/`original_size_bytes`
 * so the loss is visible in Loki rather than silent. Mirrors `_truncated_entry`
 * in `libs/shared/py/logging.py`.
 */
function capLineSize(record: Record<string, JsonValue>, line: string): string {
  const originalSizeBytes = Buffer.byteLength(line, "utf8");
  if (originalSizeBytes <= MAX_JSON_LINE_BYTES) return line;

  const truncated: Record<string, JsonValue> = {};
  for (const key of ENVELOPE_KEYS) truncated[key] = record[key];
  truncated.message = String(record.message).slice(
    0,
    TRUNCATED_MESSAGE_MAX_CHARS,
  );
  if (record.trace_id !== undefined) truncated.trace_id = record.trace_id;
  truncated.line_truncated = true;
  truncated.original_size_bytes = originalSizeBytes;
  return JSON.stringify(truncated);
}

/**
 * Serializes and writes one canonical JSON log line. The single low-level
 * emitter shared by {@link createBotLogger} and the wide-event runtime
 * (`wide-events.ts`), so every line carries the same envelope
 * (time/level/env/service/logger/platform/component/message).
 *
 * The same line goes to stdout (scraped by Promtail's Docker service-discovery
 * job) and to the local structured file sink (scraped by Promtail's file job
 * when the bot runs outside Docker) — see `log-file-sink.ts`.
 */
export function emitBotLogLine(
  level: BotLogLevel,
  platform: PlatformName | "shared",
  component: string,
  event: string,
  fields?: BotLogFields,
  error?: unknown,
): void {
  const time = new Date().toISOString();
  const record = buildRecord(
    time,
    level,
    platform,
    component,
    event,
    fields,
    error,
  );
  const line = capLineSize(record, JSON.stringify(record));
  write(level, line);
  appendStructuredLogLine(time, line);
}

export function createBotLogger(
  platform: PlatformName | "shared",
  component: string,
): BotLogger {
  return {
    debug: (event, fields) =>
      emitBotLogLine("debug", platform, component, event, fields),
    info: (event, fields) =>
      emitBotLogLine("info", platform, component, event, fields),
    warn: (event, fields) =>
      emitBotLogLine("warn", platform, component, event, fields),
    error: (event, fields, error) =>
      emitBotLogLine("error", platform, component, event, fields, error),
  };
}
