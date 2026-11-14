import { ApiError, REQUEST_ID_HEADER } from "@shared/api";
import type { paths } from "@shared/api/generated";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import createClient from "openapi-fetch";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import { toApiOrigin } from "./origin";

/** A visitor's render fails fast rather than hold the response on a slow API. */
const REQUEST_TIMEOUT_MS = 10_000;

interface ServerReadOptions {
  /** Seconds the response is served from Next's data cache before it is refetched. */
  readonly revalidate?: number;
}

/** Fetch with the request timeout; throws during the build, which renders no API data. */
export async function serverFetch(
  request: Request,
  { revalidate }: ServerReadOptions = {},
): Promise<Response> {
  if (process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD) {
    throw new Error(
      `${request.method} ${request.url} ran during the build. A page that reads the API renders at request time: return [] from its generateStaticParams, or call connection() before the read.`,
    );
  }
  return fetch(request.clone(), {
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    ...(revalidate === undefined ? {} : { next: { revalidate } }),
  });
}

/**
 * The typed client for server components and route handlers.
 *
 * Same generated `paths` as the browser client, but over the server-only base
 * (`API_BASE_URL_INTERNAL`) and plain fetch: no cookies, no interceptors, no
 * toasts. Returns null when no base is configured, like getServerApiBaseUrl.
 */
export function serverApi(options: ServerReadOptions = {}) {
  const base = getServerApiBaseUrl();
  if (!base) return null;
  return createClient<paths>({
    baseUrl: toApiOrigin(base),
    fetch: (request) => serverFetch(request, options),
  });
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
