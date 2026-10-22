import type { SetupStatusResponse } from "@shared/api/generated";
import { connection } from "next/server";

import { isSelfhostWeb } from "@/lib/selfhost";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

/**
 * Server-side GET /setup/status via the SSR base URL (internal, then public),
 * read per request. Self-host only: hosted GAIA mounts no /setup routes.
 * Throws when the API cannot answer, so the page shows its error boundary.
 */
export async function getSetupStatusServer(): Promise<SetupStatusResponse> {
  await connection();
  const apiBaseUrl = getServerApiBaseUrl();
  if (!apiBaseUrl) {
    throw new Error("API base URL not configured; cannot read setup status");
  }
  const response = await fetch(`${apiBaseUrl}/setup/status`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(
      `GET setup/status failed: ${response.status} ${response.statusText}`,
    );
  }
  return (await response.json()) as SetupStatusResponse;
}

/** The instance auth mode for a server-rendered auth page; hosted GAIA is always WorkOS. */
export async function resolveInstanceAuthMode(): Promise<
  SetupStatusResponse["auth_mode"]
> {
  if (!isSelfhostWeb()) return "workos";
  return (await getSetupStatusServer()).auth_mode;
}
