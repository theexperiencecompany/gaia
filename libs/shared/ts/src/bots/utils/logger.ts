import { createHash, createHmac } from "node:crypto";
import type { PlatformName } from "../types";

type BotLogLevel = "debug" | "info" | "warn" | "error";

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
  "platform",
  "component",
  "event",
  "error",
]);

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
  if (level === "info") {
    console.log(line);
    return;
  }
  if (level === "warn") {
    console.warn(line);
    return;
  }
  console.error(line);
}

function buildRecord(
  level: BotLogLevel,
  platform: PlatformName | "shared",
  component: string,
  event: string,
  fields?: BotLogFields,
  error?: unknown,
): Record<string, JsonValue> {
  const record: Record<string, JsonValue> = {
    time: new Date().toISOString(),
    level: level.toUpperCase(),
    env: process.env.NODE_ENV ?? "development",
    service: platform === "shared" ? "gaia-bots" : `gaia-bot-${platform}`,
    platform,
    component,
    event,
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

export function createBotLogger(
  platform: PlatformName | "shared",
  component: string,
): BotLogger {
  const emit = (
    level: BotLogLevel,
    event: string,
    fields?: BotLogFields,
    error?: unknown,
  ) => {
    const record = buildRecord(
      level,
      platform,
      component,
      event,
      fields,
      error,
    );
    write(level, JSON.stringify(record));
  };

  return {
    debug: (event, fields) => emit("debug", event, fields),
    info: (event, fields) => emit("info", event, fields),
    warn: (event, fields) => emit("warn", event, fields),
    error: (event, fields, error) => emit("error", event, fields, error),
  };
}
