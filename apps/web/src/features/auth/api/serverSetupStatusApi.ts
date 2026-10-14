import type { SetupStatusResponse } from "@gaia/shared/api/generated";
import { connection } from "next/server";

import { isSelfhostWeb } from "@/lib/selfhost";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

/**
 * Server-side `GET /setup/status` via the SSR base URL (internal → public).
 * Null on hosted GAIA, which mounts no /setup routes, and when unconfigured
 * or unreachable so callers fall back to the WorkOS redirect.
 */
export async function getSetupStatusServer(): Promise<SetupStatusResponse | null> {
  if (!isSelfhostWeb()) return null;
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
 * API's `GET /setup/status`; hosted GAIA and an unreachable probe resolve to
 * "workos". A self-host page reads it per request, never at build time.
 */
export async function resolveInstanceAuthMode(): Promise<
  SetupStatusResponse["auth_mode"]
> {
  if (!isSelfhostWeb()) return "workos";
  await connection();
  const setupStatus = await getSetupStatusServer();
  return setupStatus?.auth_mode ?? "workos";
}
