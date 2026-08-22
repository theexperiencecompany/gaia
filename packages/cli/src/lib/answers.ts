/**
 * Answer sourcing for `gaia up`.
 *
 * `up` is zero-prompt by default: every prompt id the setup pipeline can ask
 * for resolves BEFORE `store.waitForInput()` blocks, through a precedence
 * chain of CLI flags → saved values (~/.gaia/config.json) → infrastructure
 * defaults. The resolver is registered on the store (see
 * `CLIStore.pushAnswerResolver`) so the existing env-setup pipeline runs
 * unchanged — it simply never blocks.
 *
 * Secrets are never defaulted silently: a secret-shaped value that cannot be
 * resolved fails loudly naming the flag that provides it.
 * @module lib/answers
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { readConfig } from "./config.js";
import {
  getDefaultValue,
  getInfrastructureVariables,
  loadVendoredSchema,
  type SetupMode,
} from "./env-parser.js";
import { isInteractive } from "./non-tty.js";

export type LlmProvider = "openrouter" | "gemini" | "custom";

export interface UpFlags {
  /** Accept all defaults — implied for every prompt `up` can resolve. */
  yes?: boolean;
  llmKey?: string;
  llmProvider?: LlmProvider;
  apiPort?: number;
  webPort?: number;
  pull?: boolean;
  build?: boolean;
  noStart?: boolean;
  /** Confirm operating on a developer checkout that is not the recorded install. */
  forceDevTree?: boolean;
}

/**
 * Maps env vars to the flag that sources them — used to fail loud naming the
 * flag instead of silently continuing when a value is missing in non-TTY runs.
 */
const ENV_VAR_FLAG_HINTS: Record<string, string> = {
  OPENROUTER_API_KEY: "--llm-key --llm-provider openrouter",
  GOOGLE_API_KEY: "--llm-key --llm-provider gemini",
};

/** Env var each provider flag writes for first boot ("custom" writes none). */
export const PROVIDER_ENV_VAR: Record<
  Exclude<LlmProvider, "custom">,
  string
> = {
  openrouter: "OPENROUTER_API_KEY",
  gemini: "GOOGLE_API_KEY",
};

/** Default install location for fresh self-host clones (mirrors init). */
export const DEFAULT_INSTALL_DIR = path.join(os.homedir(), "gaia");

/**
 * The recorded install directory from ~/.gaia/config.json, but only when it
 * still looks like a valid GAIA checkout. Returns null when nothing (valid)
 * is recorded.
 */
export function resolveRecordedInstall(): string | null {
  const recorded = readConfig()?.repoPath;
  if (
    recorded &&
    fs.existsSync(
      path.join(recorded, "apps/api/app/config/settings_validator.py"),
    )
  ) {
    return recorded;
  }
  return null;
}

/**
 * Validate flag combinations before any side effect. Every failure names the
 * flag that fixes it — no silent defaults for secrets.
 */
export function validateLlmFlags(flags: UpFlags): void {
  if (flags.llmProvider === "custom") {
    if (flags.llmKey) {
      throw new Error(
        "--llm-key is not used with --llm-provider custom. Custom providers are configured at runtime in the web setup wizard after boot.",
      );
    }
    return;
  }
  if (flags.llmKey && !flags.llmProvider) {
    throw new Error(
      "--llm-key requires --llm-provider <openrouter|gemini|custom>.",
    );
  }
  if (flags.llmProvider && !flags.llmKey) {
    throw new Error(
      `--llm-provider ${flags.llmProvider} requires an API key: add --llm-key <key>.`,
    );
  }
}

/**
 * Port overrides explicitly requested via --api-port/--web-port. These win
 * over conflict-derived alternatives (explicit user intent).
 */
export function portOverridesFromFlags(flags: UpFlags): Record<number, number> {
  const overrides: Record<number, number> = {};
  if (flags.apiPort) overrides[8000] = flags.apiPort;
  if (flags.webPort) overrides[3000] = flags.webPort;
  return overrides;
}

/**
 * Saved non-secret answers from previous runs (~/.gaia/config.json).
 *
 * Only non-secrets belong here (ports, paths); provider keys must come from
 * flags or the web wizard, never persisted to disk by the CLI.
 */
function readSavedValues(): Record<string, string> {
  return readConfig()?.values ?? {};
}

function findSchemaVar(name: string) {
  return loadVendoredSchema()
    .flatMap((c) => c.variables)
    .find((v) => v.name === name);
}

/**
 * Build the store answer resolver implementing the precedence chain:
 * CLI flags → saved config values → INFRASTRUCTURE_DEFAULTS.
 *
 * `interactive` reflects TTY availability at call time; in non-interactive
 * runs a schema-required variable that no layer can resolve throws naming
 * the flag that provides it instead of blocking forever or writing a silent
 * default.
 */
export function createUpAnswerResolver(input: {
  flags: UpFlags;
  repoPath: string;
  interactive?: boolean;
  setupMode?: SetupMode;
}): (id: string, meta?: unknown) => unknown {
  const {
    flags,
    repoPath,
    interactive = isInteractive(),
    setupMode = "selfhost",
  } = input;
  const savedValues = readSavedValues();
  const infraVars = new Set(getInfrastructureVariables());
  const schemaCache = new Map<string, boolean>();
  const isRequired = (name: string): boolean => {
    if (!schemaCache.has(name)) {
      schemaCache.set(name, findSchemaVar(name)?.required === true);
    }
    return schemaCache.get(name) === true;
  };

  const flagEnvValues: Record<string, string> = {};
  if (flags.llmKey && flags.llmProvider && flags.llmProvider !== "custom") {
    flagEnvValues[PROVIDER_ENV_VAR[flags.llmProvider]] = flags.llmKey;
  }

  const resolveEnvVar = (name: string): string => {
    const layered =
      flagEnvValues[name] ??
      savedValues[name] ??
      getDefaultValue(name, setupMode);
    if (layered) return layered;

    // Nothing resolved. In non-TTY runs, refuse to guess for variables the
    // schema marks required AND that a known flag could have provided.
    if (!interactive && isRequired(name)) {
      const hint = ENV_VAR_FLAG_HINTS[name];
      throw new Error(
        hint
          ? `${name} is required but missing in non-interactive mode — rerun with ${hint}, or use an interactive terminal.`
          : `${name} is required but could not be resolved in non-interactive mode — provide it via a GAIA flag or an apps/api/.env file.`,
      );
    }
    // Optional (or interactive-but-skipped) variables resolve to "" which the
    // collection loop treats as "skip / write default".
    return "";
  };

  return (id: string, meta?: unknown) => {
    switch (id) {
      case "setup_mode":
        return "selfhost";
      case "env_method":
        return "manual";
      case "env_alternatives":
        // Provider selection moves to the web wizard; flag-supplied keys are
        // merged into env values directly.
        return { selectedGroups: [], values: { ...flagEnvValues } };
      case "env_group":
        // Multi-var groups are wizard material; skip entirely.
        return {};
      case "env_var": {
        const varName = (meta as { varName?: string } | undefined)?.varName;
        if (!varName || infraVars.has(varName)) {
          // Infra vars are pre-applied from defaults; answer skip to be safe.
          return "";
        }
        return resolveEnvVar(varName);
      }
      case "repo_path":
        return repoPath;
      case "existing_repo":
        return "use_existing";
      case "port_conflicts":
        return "accept";
      default:
        // Unknown ids (e.g. "docker_install_confirm", "exit") fall through to
        // the interactive prompt / command-runner auto-resolve handling.
        return undefined;
    }
  };
}
