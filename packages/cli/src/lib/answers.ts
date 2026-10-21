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
 * Secrets are never defaulted silently: a required value that cannot be
 * resolved fails loudly. The AI provider flags are not env answers at all —
 * see lib/llm-flags.
 * @module lib/answers
 */

import * as os from "node:os";
import * as path from "node:path";
import { readConfig } from "./config.js";
import { DEFAULT_HTTPS_PORT, DEFAULT_WEB_PORT } from "./endpoints.js";
import {
  getDefaultValue,
  getInfrastructureVariables,
  loadVendoredSchema,
  type SetupMode,
} from "./env-parser.js";
import type { DomainFlag } from "./env-writer.js";
import type { LlmFlags } from "./llm-flags.js";
import { isInteractive } from "./non-tty.js";
import type { PortConflictPolicy, PortPlan } from "./port-conflicts.js";
import { isGaiaInstall } from "./service-starter.js";

export interface UpFlags extends LlmFlags {
  /** Accept all defaults — implied for every prompt `up` can resolve. */
  yes?: boolean;
  webPort?: number;
  /** Public domain; the proxy serves HTTPS for it on 80/443. False on --no-domain. */
  domain?: DomainFlag;
  build?: boolean;
  /**
   * Opt in (true) or out (false) of the Docker-socket code sandbox; undefined
   * keeps the saved choice.
   */
  codeSandbox?: boolean;
  noStart?: boolean;
  /** False on --no-local-name: no gaia.local on the network. */
  localName?: boolean;
  /** Confirm operating on a developer checkout that is not the recorded install. */
  forceDevTree?: boolean;
}

const HTTP_PORT = 80;
const HTTPS_PORT = 443;

/** Default install location for fresh self-host clones (mirrors init). */
export const DEFAULT_INSTALL_DIR = path.join(os.homedir(), "gaia");

/**
 * The recorded install directory from ~/.gaia/config.json, but only when it
 * still looks like a valid GAIA checkout. Returns null when nothing (valid)
 * is recorded.
 */
export function resolveRecordedInstall(): string | null {
  const recorded = readConfig()?.repoPath;
  return recorded && isGaiaInstall(recorded) ? recorded : null;
}

/**
 * The host ports --web-port/--domain pin, which a conflict never moves. A
 * domain needs the standard ports: 80 for the ACME challenge and redirect,
 * 443 for HTTPS.
 */
export function pinnedPorts(
  flags: Pick<UpFlags, "domain" | "webPort">,
): Pick<PortPlan, "planned" | "fixed"> {
  const plan: Pick<PortPlan, "planned" | "fixed"> = { planned: {}, fixed: {} };
  if (flags.domain) {
    plan.planned[DEFAULT_WEB_PORT] = HTTP_PORT;
    plan.planned[DEFAULT_HTTPS_PORT] = HTTPS_PORT;
    plan.fixed[DEFAULT_WEB_PORT] = "domain";
    plan.fixed[DEFAULT_HTTPS_PORT] = "domain";
  } else if (flags.domain === false) {
    // Off the domain's 80/443; a taken default still moves like any other port.
    plan.planned[DEFAULT_WEB_PORT] = DEFAULT_WEB_PORT;
    plan.planned[DEFAULT_HTTPS_PORT] = DEFAULT_HTTPS_PORT;
  }
  if (flags.webPort) {
    plan.planned[DEFAULT_WEB_PORT] = flags.webPort;
    plan.fixed[DEFAULT_WEB_PORT] = "web-port";
  }
  return plan;
}

/** `gaia up` never asks about a taken port: it moves it (and says so), or in a script without --yes it stops. */
export function portConflictPolicy(
  flags: Pick<UpFlags, "yes">,
  interactive: boolean = isInteractive(),
): PortConflictPolicy {
  return flags.yes || interactive ? "move" : "fail";
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
 * saved config values → INFRASTRUCTURE_DEFAULTS.
 *
 * `interactive` reflects TTY availability at call time; in non-interactive
 * runs a schema-required variable that no layer can resolve throws instead
 * of blocking forever or writing a silent default.
 */
export function createUpAnswerResolver(input: {
  repoPath: string;
  interactive?: boolean;
  setupMode?: SetupMode;
}): (id: string, meta?: unknown) => unknown {
  const {
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

  const resolveEnvVar = (name: string): string => {
    const layered = savedValues[name] ?? getDefaultValue(name, setupMode);
    if (layered) return layered;

    // Nothing resolved. In non-TTY runs, refuse to guess for variables the
    // schema marks required.
    if (!interactive && isRequired(name)) {
      throw new Error(
        `${name} is required but could not be resolved in non-interactive mode — provide it via a GAIA flag or an apps/api/.env file.`,
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
        // Provider selection is the web wizard's, or --llm-provider's after boot.
        return { selectedGroups: [], values: {} };
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
      default:
        // Unknown ids (e.g. the install confirmations, "exit") fall through to
        // the interactive prompt / command-runner auto-resolve handling.
        return undefined;
    }
  };
}
