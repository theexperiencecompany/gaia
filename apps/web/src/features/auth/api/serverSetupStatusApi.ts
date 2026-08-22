import type { SetupStatus } from "@/features/settings/api/providersApi";

import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

/**
 * Server-side fetch of the public `GET /setup/status` probe (self-host
 * contract in `.agents/plans/selfhost-contracts.md`). Goes through the SSR
 * base URL (API_BASE_URL_INTERNAL → NEXT_PUBLIC_API_BASE_URL) — the public
 * browser URL is often unreachable from inside the web container on deploys.
 * `cache: "no-store"` keeps auth-mode switching live: the login/signup pages
 * must reflect the instance's actual mode on every visit.
 *
 * Returns null (with a logged error) when unconfigured or unreachable, so
 * callers fall back to the classic WorkOS redirect instead of breaking the
 * page.
 */
export async function getSetupStatusServer(): Promise<SetupStatus | null> {
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
    return (await response.json()) as SetupStatus;
  } catch (error) {
    console.error("[auth] Failed to fetch setup status:", error);
    return null;
  }
}
