import { ApiError } from "@shared/api";
import type { ConnectLinkPreviewResponse } from "@shared/api/generated";

import { api } from "@/lib/api/typed";

const HTTP_NOT_FOUND = 404;

/**
 * What a bot connect link will connect, and for which account, without
 * spending its code. Null when the code is unknown, used or expired. Called
 * from the visitor's browser, so the API rate-limits the visitor, not GAIA's
 * web server.
 */
export async function previewConnectLink(
  code: string,
): Promise<ConnectLinkPreviewResponse | null> {
  try {
    return await api.post("/api/v1/integrations/connect-link/preview", {
      body: { code },
      silent: true,
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === HTTP_NOT_FOUND) {
      return null;
    }
    throw error;
  }
}
