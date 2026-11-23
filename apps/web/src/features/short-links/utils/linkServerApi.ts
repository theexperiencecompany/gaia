import type { LinkResolution } from "@/features/short-links/types";
import { linkUnavailableState } from "@/features/short-links/utils/linkDenial";
import { internalApiHeaders } from "@/lib/internalApiHeaders";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import type {
  ErrorEnvelope,
  LinkEnvelope,
  LinkPreviewMeta,
} from "@/types/features/shortLinkTypes";

const HTTP_TOO_MANY_REQUESTS = 429;

/** What /meta answered, and how long the API says it may be cached. */
export interface LinkMetaReply {
  meta: LinkPreviewMeta;
  cacheControl: string | null;
}

/**
 * Call the link API from the server as the viewer `viewer` names: never cached,
 * since the owner can revoke or narrow a link at any moment, and rate-limited
 * per viewer rather than per server.
 */
async function linkApiFetch(path: string, viewer: Headers): Promise<Response> {
  const apiBaseUrl = getServerApiBaseUrl();
  if (!apiBaseUrl) {
    throw new Error("API base URL is not configured for server rendering");
  }
  return fetch(`${apiBaseUrl}${path}`, {
    cache: "no-store",
    headers: internalApiHeaders(viewer),
  });
}

/**
 * What a preview may show for the link. Null when the viewer is refused for
 * opening too many links; the page says so from the resolve's own refusal.
 */
export async function fetchLinkMeta(
  slug: string,
  viewer: Headers,
): Promise<LinkMetaReply | null> {
  const response = await linkApiFetch(
    `/l/${encodeURIComponent(slug)}/meta`,
    viewer,
  );
  if (response.status === HTTP_TOO_MANY_REQUESTS) return null;
  if (!response.ok) {
    // Never the slug: it is a working link, and this message reaches Sentry.
    throw new Error(`Short link meta failed with ${response.status}`);
  }
  const meta: LinkPreviewMeta = await response.json();
  return { meta, cacheControl: response.headers.get("cache-control") };
}

/**
 * Open the link as the server sees the viewer: never their session, so a
 * owner-only link answers a sign-in denial and is opened again from the browser.
 */
export async function resolveLinkOnServer(
  slug: string,
  viewer: Headers,
): Promise<LinkResolution> {
  const response = await linkApiFetch(`/l/${encodeURIComponent(slug)}`, viewer);
  if (response.ok) {
    const envelope: LinkEnvelope = await response.json();
    return { kind: "open", envelope };
  }
  const envelope: ErrorEnvelope | undefined = await response
    .json()
    .catch(() => undefined);
  const state = linkUnavailableState(slug, envelope);
  if (!state) {
    throw new Error(`Short link resolve failed with ${response.status}`);
  }
  return { kind: "unavailable", state };
}
