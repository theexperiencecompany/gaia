/**
 * Per-dependency readiness from the API's `GET /health/ready`, with the fix
 * an operator should try for each failing dependency. Shared by `gaia status`
 * and `gaia doctor`.
 * @module lib/dependency-readiness
 */

import type {
  DependencyStatus,
  ReadinessResponse,
} from "@gaia/shared/api/generated";
import type { ComposeProject } from "./docker.js";

/** The endpoint answers in ~2s worst case (its per-check bound); allow margin. */
const READINESS_TIMEOUT_MS = 5_000;

/** HTTP status /health/ready returns when a dependency failed its check. */
const NOT_READY_STATUS = 503;

/** One dependency's check plus the fix to show when it failed. */
export interface DependencyCheck extends DependencyStatus {
  fix?: string;
}

export type DependencyReadiness =
  | { reachable: true; ready: boolean; dependencies: DependencyCheck[] }
  | { reachable: false; detail: string };

/** Compose service and the likely cause, per dependency name the API reports. */
const DEPENDENCY_HINTS: Record<string, { service: string; cause: string }> = {
  mongodb: {
    service: "mongo",
    cause:
      "a full disk is the usual cause; users, chats and settings live here",
  },
  postgres: {
    service: "postgres",
    cause: "a full disk is the usual cause; agent state lives here",
  },
  redis: {
    service: "redis",
    cause: "background jobs and reminders queue here and wait until it is back",
  },
  rabbitmq: {
    service: "rabbitmq",
    cause: "it takes up to a minute to boot after a restart, so rerun first",
  },
  chromadb: {
    service: "chromadb",
    cause: "memory and file search stay unavailable until it answers",
  },
};

/** The command and likely cause for one failing dependency. */
function dependencyFix(name: string, project: ComposeProject): string {
  const hint = DEPENDENCY_HINTS[name];
  if (!hint) {
    return `Check the API logs: docker compose -p ${project} logs gaia-backend`;
  }
  return `Check its logs: docker compose -p ${project} logs ${hint.service} (${hint.cause}).`;
}

/** Ask the API at `origin` which backing services answer a real request. */
export async function fetchDependencyReadiness(
  origin: string,
  project: ComposeProject,
): Promise<DependencyReadiness> {
  let res: Response;
  try {
    res = await fetch(`${origin}/health/ready`, {
      signal: AbortSignal.timeout(READINESS_TIMEOUT_MS),
    });
  } catch (e) {
    return {
      reachable: false,
      detail: `Could not reach ${origin}/health/ready: ${(e as Error).message}`,
    };
  }
  if (!res.ok && res.status !== NOT_READY_STATUS) {
    return {
      reachable: false,
      detail: `HTTP ${res.status} from ${origin}/health/ready`,
    };
  }
  const body = (await res.json()) as ReadinessResponse;
  return {
    reachable: true,
    ready: body.status === "ready",
    dependencies: body.dependencies.map((dependency) =>
      dependency.ok
        ? dependency
        : { ...dependency, fix: dependencyFix(dependency.name, project) },
    ),
  };
}
