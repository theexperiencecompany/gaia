import type { SetupStatusResponse } from "@gaia/shared/api/generated";

import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

/**
 * Server-side `GET /setup/status` via the SSR base URL (internal → public).
 * `cache: "no-store"` keeps auth-mode switching live on every visit.
 * Returns null when unconfigured or unreachable so callers fall back
 * to the WorkOS redirect.
 */
async function getSetupStatusServer(): Promise<SetupStatusResponse | null> {
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
 * Resolve the instance auth mode for server-rendered auth pages.
 * Prefers static AUTH_MODE, else the live `GET /setup/status` probe.
 * Invalid env values warn and defer to the probe; unreachable probes
 * resolve to "workos".
 */
export async function resolveInstanceAuthMode(): Promise<
  SetupStatusResponse["auth_mode"]
> {
  const envAuthMode = process.env.AUTH_MODE;
  if (envAuthMode) {
    if (envAuthMode === "workos" || envAuthMode === "local") {
      return envAuthMode;
    }
    console.error(
      `[auth] Ignoring invalid AUTH_MODE "${envAuthMode}" (expected "workos" or "local")`,
    );
  }
  const setupStatus = await getSetupStatusServer();
  return setupStatus?.auth_mode ?? "workos";
}
