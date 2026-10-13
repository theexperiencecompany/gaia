import type { ReferralResolveResponse } from "@shared/api/generated";
import { serverApi, serverApiError } from "@/lib/api/server";

const RESOLVE_TIMEOUT_MS = 5_000;
/** A referrer's name, photo and gift price change rarely; an hour-old preview is fine. */
const RESOLVE_CACHE_SECONDS = 60 * 60;

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
      // Next's data cache (R2-backed under OpenNext) keeps one answer per code, so a burst of
      // link unfurls from this server's single IP never reaches the API's per-IP limit.
      fetch: (request) =>
        fetch(request, { next: { revalidate: RESOLVE_CACHE_SECONDS } }),
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
