import { ApiError, REQUEST_ID_HEADER } from "@shared/api";
import type { paths } from "@shared/api/generated";
import createClient from "openapi-fetch";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import { toApiOrigin } from "./origin";

/**
 * The typed client for server components and route handlers.
 *
 * Same generated `paths` as the browser client, but over the server-only base
 * (`API_BASE_URL_INTERNAL`) and plain fetch: no cookies, no interceptors, no
 * toasts. Returns null when no base is configured, like getServerApiBaseUrl.
 */
export function serverApi() {
  const base = getServerApiBaseUrl();
  if (!base) return null;
  return createClient<paths>({ baseUrl: toApiOrigin(base) });
}

/** Turn a failed openapi-fetch result into the shared ApiError. */
export function serverApiError(response: Response, body: unknown): ApiError {
  return ApiError.fromBody(response.status, body, {
    requestId: response.headers.get(REQUEST_ID_HEADER) ?? undefined,
  });
}
