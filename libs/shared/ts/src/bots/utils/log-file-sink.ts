/**
 * Local NDJSON file sink for bot logs — the TypeScript twin of
 * `_json_file_sink_factory` / `_prune_structured_logs` in
 * `libs/shared/py/logging.py`.
 *
 * Every line the bots write to stdout is also appended to
 * `<logDir>/structured-<YYYY-MM-DD>.json`, so a bot started with `nx dev`
 * reaches Loki through Promtail's *file* job (`gaia_bots_local` in
 * infra/docker/observability/promtail-config.yaml) exactly like the locally-run
 * Python services do. Inside Docker the file sink stays off: there the Docker
 * service-discovery job already scrapes container stdout, so writing files
 * would only burn disk.
 *
 * Directory resolution (one rule, no magic):
 *
 * - `BOT_LOG_DIR` set to a non-empty path → that directory wins (set it to an
 *   empty string to explicitly disable the sink).
 * - `BOT_LOG_DIR` unset → `<cwd>/logs`, but only when the process was started
 *   from a bot package directory (`apps/bots/<platform>`), which is what
 *   `nx dev bot-<platform>` does. The bot image runs with WORKDIR `/app`, so
 *   no default resolves there and the sink stays disabled.
 *
 * The sink must never take a bot down: the first write/open/prune failure
 * disables it permanently and reports once on stderr, leaving stdout — the
 * canonical stream — untouched.
 */
import {
  closeSync,
  mkdirSync,
  openSync,
  readdirSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import path from "node:path";
import type { PlatformName } from "../types";

/** Matches STRUCTURED_LOG_RETENTION_DAYS in libs/shared/py/logging.py. */
const STRUCTURED_LOG_RETENTION_DAYS = 30;

const STRUCTURED_LOG_PREFIX = "structured-";
const STRUCTURED_LOG_SUFFIX = ".json";
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const MS_PER_DAY = 86_400_000;

/** Bot package directory names — the `apps/bots/<platform>` leaf. */
const BOT_PLATFORM_DIRS: ReadonlySet<string> = new Set<PlatformName>([
  "discord",
  "slack",
  "telegram",
  "whatsapp",
]);

let dirResolved = false;
let cachedDir: string | null = null;
let handle: number | null = null;
let handleDate = "";
let disabled = false;

function resolveLogDir(): string | null {
  const configured = process.env.BOT_LOG_DIR;
  if (configured !== undefined) {
    const trimmed = configured.trim();
    return trimmed === "" ? null : path.resolve(trimmed);
  }

  const cwd = process.cwd();
  if (!BOT_PLATFORM_DIRS.has(path.basename(cwd))) return null;
  if (path.basename(path.dirname(cwd)) !== "bots") return null;
  return path.join(cwd, "logs");
}

function logDirectory(): string | null {
  if (!dirResolved) {
    cachedDir = resolveLogDir();
    dirResolved = true;
  }
  return cachedDir;
}

/**
 * Delete `structured-*.json` files older than the retention window. Called on
 * every handle open, i.e. once per process and again on each date rollover —
 * same trigger points as the Python sink. A file exactly
 * STRUCTURED_LOG_RETENTION_DAYS old is kept (the cutoff is inclusive).
 */
function pruneStructuredLogs(logDir: string, today: string): void {
  const cutoff =
    Date.parse(`${today}T00:00:00Z`) -
    STRUCTURED_LOG_RETENTION_DAYS * MS_PER_DAY;

  for (const name of readdirSync(logDir)) {
    if (!name.startsWith(STRUCTURED_LOG_PREFIX)) continue;
    if (!name.endsWith(STRUCTURED_LOG_SUFFIX)) continue;

    const stamp = name.slice(
      STRUCTURED_LOG_PREFIX.length,
      -STRUCTURED_LOG_SUFFIX.length,
    );
    // Not one of ours — a foreign file matching the glob.
    if (!ISO_DATE_PATTERN.test(stamp)) continue;

    const fileDate = Date.parse(`${stamp}T00:00:00Z`);
    if (Number.isNaN(fileDate) || fileDate >= cutoff) continue;

    try {
      unlinkSync(path.join(logDir, name));
    } catch (error) {
      // Inside the log sink — reporting via the logger would recurse.
      process.stderr.write(
        `[gaia-bot-logging] failed to prune old log ${name}: ${describe(error)}\n`,
      );
    }
  }
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Append one already-serialized JSON log line to today's structured file.
 *
 * `isoTime` is the line's own `time` field, so the file a line lands in always
 * agrees with the timestamp it carries — including the line that straddles
 * midnight and triggers the rollover.
 */
export function appendStructuredLogLine(isoTime: string, line: string): void {
  if (disabled) return;

  const logDir = logDirectory();
  if (logDir === null) {
    disabled = true;
    return;
  }

  const date = isoTime.slice(0, 10);
  try {
    if (handle === null || date !== handleDate) {
      if (handle !== null) {
        closeSync(handle);
        handle = null;
      }
      mkdirSync(logDir, { recursive: true });
      pruneStructuredLogs(logDir, date);
      handle = openSync(
        path.join(
          logDir,
          `${STRUCTURED_LOG_PREFIX}${date}${STRUCTURED_LOG_SUFFIX}`,
        ),
        "a",
      );
      handleDate = date;
    }
    writeSync(handle, `${line}\n`);
  } catch (error) {
    // Degrade to stdout-only rather than taking the bot down; say so once.
    disabled = true;
    handle = null;
    process.stderr.write(
      `[gaia-bot-logging] structured file sink disabled (${logDir}): ${describe(error)}\n`,
    );
  }
}
