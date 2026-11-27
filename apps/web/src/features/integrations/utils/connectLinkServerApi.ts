import type { ConnectLinkPreviewResponse } from "@shared/api/generated";

import { internalApiHeaders } from "@/lib/internalApiHeaders";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

const HTTP_NOT_FOUND = 404;

/**
 * What a bot connect link will connect, and for which account, without
 * spending its code. Null when the code is unknown, used or expired. Sent as
 * the viewer so the API's per-address limit counts them, not this server.
 */
export async function fetchConnectLinkPreview(
  code: string,
  viewer: Headers,
): Promise<ConnectLinkPreviewResponse | null> {
  const apiBaseUrl = getServerApiBaseUrl();
  if (!apiBaseUrl) {
    throw new Error("API base URL is not configured for server rendering");
  }
  const response = await fetch(
    `${apiBaseUrl}/integrations/connect-link/preview`,
    {
      method: "POST",
      cache: "no-store",
      headers: internalApiHeaders(viewer),
      body: new URLSearchParams({ code }),
    },
  );
  if (response.status === HTTP_NOT_FOUND) return null;
  if (!response.ok) {
    // Never the code: it is a live credential, and this message reaches Sentry.
    throw new Error(`Connect link preview failed with ${response.status}`);
  }
  const preview: ConnectLinkPreviewResponse = await response.json();
  return preview;
}
