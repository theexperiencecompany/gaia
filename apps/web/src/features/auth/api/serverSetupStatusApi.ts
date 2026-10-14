import type { SetupStatusResponse } from "@gaia/shared/api/generated";

import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

/**
 * Server-side `GET /setup/status` via the SSR base URL (internal → public).
 * `cache: "no-store"` keeps auth-mode switching live on every visit.
 * Returns null when unconfigured or unreachable so callers fall back
 * to the WorkOS redirect.
 */
export async function getSetupStatusServer(): Promise<SetupStatusResponse | null> {
  const apiBaseUrl = getServerApiBaseUrl();
  if (!apiBaseUrl) {
    console.error(
      "[auth] API base URL not configured; cannot read setup status",
    );
    return null;
  }

  try {
    const response = await fetch(`${apiBaseUrl}/setup/status`, {
      cache: "no-store",
    });
    if (!response.ok) {
      console.error(
        `[auth] GET setup/status failed: ${response.status} ${response.statusText}`,
      );
      return null;
    }
    return (await response.json()) as SetupStatusResponse;
  } catch (error) {
    console.error("[auth] Failed to fetch setup status:", error);
    return null;
  }
}

/**
 * Resolve the instance auth mode for server-rendered auth pages from the
 * API's `GET /setup/status`; an unreachable probe resolves to "workos".
 */
export async function resolveInstanceAuthMode(): Promise<
  SetupStatusResponse["auth_mode"]
> {
  const setupStatus = await getSetupStatusServer();
  return setupStatus?.auth_mode ?? "workos";
}

/**
 * Whether this web server fronts a self-hosted instance: the self-host compose
 * and deploy templates set GAIA_SELFHOST=true, hosted GAIA never does. Never
 * touches the network; what the instance does comes from GET /setup/status.
 */
export function isSelfhostWeb(): boolean {
  return process.env.GAIA_SELFHOST === "true";
}
