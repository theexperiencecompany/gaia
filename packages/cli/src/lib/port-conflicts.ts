/**
 * What to do about host ports another program holds: move to a free one,
 * ask, or stop with the one line that says what to free or which flag to pass.
 * A port a flag pinned (a domain's 80/443, --web-port) never moves.
 * @module lib/port-conflicts
 */

import { DEFAULT_WEB_PORT } from "./endpoints.js";
import type { PortCheckResult } from "./prerequisites.types.js";

/** Why a port must stay where it is: a domain needs 80/443, --web-port is the user's choice. */
export type FixedPortReason = "domain" | "web-port";

/** "ask": the prompt; "move": take the free alternative (--yes); "fail": no terminal to ask. */
export type PortConflictPolicy = "ask" | "move" | "fail";

export interface PortPlan {
  /** The host port each default port is bound to: earlier runs' choices and this run's flags. */
  planned: Record<number, number>;
  /** Default ports a flag pins, by why. */
  fixed: Partial<Record<number, FixedPortReason>>;
  policy: PortConflictPolicy;
}

export type PortResolution =
  | { overrides: Record<number, number>; moved: string[] }
  | { error: string };

/** Web servers a domain's port 80/443 is usually taken by, stopped with systemctl. */
const SYSTEMD_WEB_SERVERS: ReadonlySet<string> = new Set([
  "nginx",
  "apache2",
  "httpd",
  "caddy",
  "haproxy",
  "traefik",
  "lighttpd",
]);

function holder(result: PortCheckResult): string {
  return result.usedBy ?? "another program";
}

function stopHint(result: PortCheckResult): string {
  const name = result.usedBy;
  if (name?.startsWith("Docker container ")) {
    return `Stop it ('docker stop ${name.slice("Docker container ".length)}')`;
  }
  if (name && SYSTEMD_WEB_SERVERS.has(name)) {
    return `Stop it ('sudo systemctl stop ${name}')`;
  }
  return `Stop it (see what it is with 'sudo ss -ltnp "sport = :${result.port}"')`;
}

export function fixedPortError(
  result: PortCheckResult,
  reason: FixedPortReason,
): string {
  if (reason === "domain") {
    return (
      `Port ${result.port} is in use by ${holder(result)}, and a domain needs ports 80 and 443 (Let's Encrypt checks port 80).\n` +
      `${stopHint(result)}, then run 'gaia up' again.`
    );
  }
  const next = result.alternative
    ? `Pick a free one: gaia up --web-port ${result.alternative}`
    : "Pick another with --web-port";
  return `Port ${result.port} (--web-port) is in use by ${holder(result)}.\n${next}.`;
}

/** The line that tells a run with no terminal which flag settles a taken port. */
function unaskedConflictLine(result: PortCheckResult): string {
  const taken = `Port ${result.port} is in use by ${holder(result)}.`;
  if (result.defaultPort === DEFAULT_WEB_PORT && result.alternative) {
    return `${taken} Run 'gaia up --web-port ${result.alternative}' to use a free one.`;
  }
  return `${taken} Free it.`;
}

/**
 * The host ports to bind once conflicts are settled by the plan's policy.
 * "ask" resolutions come back as "move": the caller asks before applying them.
 */
export function resolvePortConflicts(
  results: readonly PortCheckResult[],
  plan: PortPlan,
): PortResolution {
  const conflicts = results.filter((result) => !result.available);
  for (const conflict of conflicts) {
    const reason = plan.fixed[conflict.defaultPort];
    if (reason) return { error: fixedPortError(conflict, reason) };
  }
  if (conflicts.length > 0 && plan.policy === "fail") {
    return {
      error: [
        ...conflicts.map(unaskedConflictLine),
        "Or add --yes to let 'gaia up' pick free ports itself.",
      ].join("\n"),
    };
  }
  const unresolvable = conflicts.filter((result) => !result.alternative);
  if (unresolvable.length > 0) {
    return {
      error: `Cannot find free alternative ports for: ${unresolvable.map((r) => `${r.port} (${r.service})`).join(", ")}. Free these ports and try again.`,
    };
  }
  const overrides = { ...plan.planned };
  const moved: string[] = [];
  for (const conflict of conflicts) {
    if (!conflict.alternative) continue;
    overrides[conflict.defaultPort] = conflict.alternative;
    moved.push(
      `Port ${conflict.port} was in use by ${holder(conflict)}, so GAIA uses ${conflict.alternative}.`,
    );
  }
  return { overrides, moved };
}
