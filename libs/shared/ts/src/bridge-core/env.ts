// Host-injected environment for bridge-core. The CLI leaves this unconfigured
// and gets today's exact values (state under ~/.gaia/bridge, the process env,
// $SHELL). A GUI host (the Electron desktop app) calls configureBridge() once
// at startup to point the state dir at userData/bridge and to supply a resolved
// login-shell PATH/SHELL — a Finder-launched app otherwise has a bare
// /usr/bin:/bin PATH and every spawned npx/uvx/node fails ENOENT.

import { homedir } from "node:os";
import { join } from "node:path";

export interface BridgeEnv {
  /** Base dir for credentials.json, config.json, and the exec audit log. */
  stateDir: string;
  /** Environment passed to spawned exec commands and stdio MCP servers. */
  env: NodeJS.ProcessEnv;
  /** Shell used to run `run_on_device` commands (`<shell> -c <command>`). */
  shell: string;
}

/** Diagnostics sink. The CLI leaves this unset and every line goes to stderr
 * (its historical stream). A GUI host (Electron desktop) supplies its own so
 * bridge diagnostics land in the app's log file instead of a detached stdout. */
export interface BridgeLogger {
  info(message: string, meta?: Record<string, unknown>): void;
  error(message: string, meta?: Record<string, unknown>): void;
}

// The CLI's default: both levels write to stderr, exactly where the bridge's
// console.error diagnostics have always gone, so CLI output stays byte-identical.
// The info/error split matters only for a host that injects its own logger.
const defaultLogger: BridgeLogger = {
  info: (message) => console.error(message),
  error: (message) => console.error(message),
};

let overrides: Partial<BridgeEnv> = {};
let loggerOverride: BridgeLogger | null = null;

/** Merge host-supplied values over the CLI-safe defaults. Later calls merge
 * on top of earlier ones; a field left unset keeps its default. */
export function configureBridge(
  config: Partial<BridgeEnv> & { logger?: BridgeLogger },
): void {
  const { logger, ...env } = config;
  overrides = { ...overrides, ...env };
  if (logger) loggerOverride = logger;
}

/** The current diagnostics sink — the host-injected logger, or the console-backed
 * default. Read per call so a configureBridge() after import takes effect. */
export function bridgeLogger(): BridgeLogger {
  return loggerOverride ?? defaultLogger;
}

/** The current environment, filling any unset field with the CLI's defaults.
 * Computed on every call so a configureBridge() after import takes effect. */
export function bridgeEnv(): BridgeEnv {
  return {
    stateDir: overrides.stateDir ?? join(homedir(), ".gaia", "bridge"),
    env: overrides.env ?? process.env,
    shell: overrides.shell ?? process.env["SHELL"] ?? "/bin/sh",
  };
}
