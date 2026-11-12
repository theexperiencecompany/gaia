import { ApiError, REQUEST_ID_HEADER } from "@shared/api";
import type { paths } from "@shared/api/generated";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import createClient from "openapi-fetch";
import pRetry from "p-retry";
import { cache } from "react";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import { toApiOrigin } from "./origin";

/** A build waits out a briefly slow API and still fails on an outage; a visitor's render fails fast. */
const BUILD_FETCH_POLICY = { timeoutMs: 30_000, retries: 3 } as const;
const REQUEST_FETCH_POLICY = { timeoutMs: 10_000, retries: 0 } as const;

function isProductionBuild(): boolean {
  return process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD;
}

/** Fetch with the phase's per-attempt timeout, retrying timeouts and network errors. */
export function serverFetch(request: Request): Promise<Response> {
  const { timeoutMs, retries } = isProductionBuild()
    ? BUILD_FETCH_POLICY
    : REQUEST_FETCH_POLICY;
  return pRetry(
    () => fetch(request.clone(), { signal: AbortSignal.timeout(timeoutMs) }),
    { retries },
  );
}

/**
 * Share a server read across every page one build process prerenders, keyed by its arguments.
 *
 * A running server keeps one read per request (React cache), so ISR still sees fresh data.
 * A failed read is dropped, so the next page that asks reads again instead of reusing the failure.
 */
export function sharedAcrossBuild<Args extends readonly unknown[], T>(
  read: (...args: Args) => Promise<T>,
): (...args: Args) => Promise<T> {
  const perRequest = cache(read);
  const buildReads = new Map<string, Promise<T>>();
  return (...args) => {
    if (!isProductionBuild()) return perRequest(...args);
    const key = JSON.stringify(args);
    const shared = buildReads.get(key);
    if (shared) return shared;
    const pending = read(...args);
    buildReads.set(key, pending);
    pending.catch(() => {
      if (buildReads.get(key) === pending) buildReads.delete(key);
    });
    return pending;
  };
}

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
  return createClient<paths>({
    baseUrl: toApiOrigin(base),
    fetch: serverFetch,
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
