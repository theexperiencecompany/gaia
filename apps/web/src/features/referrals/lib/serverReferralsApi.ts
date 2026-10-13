import type { ReferralResolveResponse } from "@shared/api/generated";
import { serverApi, serverApiError } from "@/lib/api/server";

const RESOLVE_TIMEOUT_MS = 5_000;

/**
 * Who sent an invite, for metadata and the link preview. A server call carries
 * no browser cookies and its Set-Cookie never reaches the visitor, so it cannot
 * claim attribution; the landing page's browser call does that.
 */
export async function resolveInviteServer(
  code: string,
): Promise<ReferralResolveResponse> {
  const client = serverApi();
  if (!client) throw new Error("No API base URL configured for server calls");
  const { data, error, response } = await client.GET(
    "/api/v1/referrals/resolve/{code}",
    {
      params: { path: { code } },
      signal: AbortSignal.timeout(RESOLVE_TIMEOUT_MS),
    },
  );
  if (error !== undefined || data === undefined) {
    const failure = serverApiError(response, error);
    throw new Error(`Failed to resolve invite code: ${failure.message}`, {
      cause: failure,
    });
  }
  return data;
}
