import type { ReferralResolveResponse } from "@shared/api/generated";
import { serverApi, serverApiError } from "@/lib/api/server";

const RESOLVE_TIMEOUT_MS = 5_000;
/** A referrer's name, photo and gift price change rarely; an hour-old preview is fine. */
const RESOLVE_CACHE_SECONDS = 60 * 60;

/**
 * Who sent an invite, for metadata and the link preview. A server call carries
 * no browser cookies and its Set-Cookie never reaches the visitor, so it cannot
 * claim attribution; the landing page's browser call does that. Null when the
 * API cannot answer: a preview falls back to generic copy rather than failing
 * the page that hosts it.
 */
export async function resolveInviteServer(
  code: string,
): Promise<ReferralResolveResponse | null> {
  const client = serverApi();
  if (!client) throw new Error("No API base URL configured for server calls");
  try {
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
    if (error === undefined && data !== undefined) return data;
    console.error(
      "Invite preview fell back to generic copy:",
      serverApiError(response, error).message,
    );
  } catch (failure) {
    console.error("Invite preview fell back to generic copy:", failure);
  }
  return null;
}
