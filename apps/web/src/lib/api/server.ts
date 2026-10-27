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

interface ServerResult<T> {
  readonly data?: T;
  readonly error?: unknown;
  readonly response: Response;
}

/** The data of a server read, or the read's failure thrown as an ApiError. */
export function serverData<T>(result: ServerResult<T>): T {
  if (result.error !== undefined || result.data === undefined) {
    throw serverApiError(result.response, result.error);
  }
  return result.data;
}

/** Like serverData, but a 404 is an answer (null) rather than a failure. */
export function serverDataOrNull<T>(result: ServerResult<T>): T | null {
  if (result.response.status === 404) return null;
  return serverData(result);
}
