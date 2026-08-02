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
export const LOG_LEVEL_NAMES: Record<BotLogLevel, string> = {
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

const RESERVED_LOG_KEYS = new Set([
  "time",
  "level",
  "env",
  "service",
  "logger",
  "platform",
  "component",
  "message",
  "error",
]);

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

export function sanitizeErrorForLog(error: unknown): BotLogFields {
  if (error instanceof Error) {
    return {
      error_name: error.name,
      error_message: error.message,
    };
  }

  return {
    error_name: "Unknown",
    error_message:
      typeof error === "string" ? error : "Unknown non-Error thrown",
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
 * `level`, `service`, `logger`, `message`, plus the wide-event fields
 * (`trace_id`, `duration_ms`, `outcome`, `errors`, `warnings`, `audit`, `env`)
 * — so a single LogQL query spans the Python services and the bots. The event
 * name lands under `message`, not `event`, for exactly that reason.
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
    env: process.env.NODE_ENV ?? "development",
    service: resolveServiceName(platform),
    // Promtail extracts `logger` into the logger_name label (see
    // infra/docker/observability/promtail-config.yaml pipeline_stages).
    logger: component,
    platform,
    component,
    message: event,
  };

  if (fields) {
    for (const [key, value] of Object.entries(fields)) {
      if (value === undefined) continue;
      const safeKey = RESERVED_LOG_KEYS.has(key) ? `field_${key}` : key;
      record[safeKey] = toJsonValue(value);
    }
  }

  if (error !== undefined) {
    record.error = toJsonValue(sanitizeErrorForLog(error));
  }

  return record;
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
  const line = JSON.stringify(record);
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
