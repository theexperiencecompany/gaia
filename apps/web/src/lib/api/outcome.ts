/**
 * What happens to the user when a request succeeds or fails.
 *
 * One place, shared by the path-typed client (./typed) and the URL-string
 * `apiService` (./service), so both toast the same way and both throw the one
 * `ApiError` with the backend's envelope already narrowed.
 */

import { ApiError, REQUEST_ID_HEADER } from "@shared/api";
import axios from "axios";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";

export interface ApiOptions {
  successMessage?: string;
  errorMessage?: string;
  silent?: boolean;
}

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

const DEFAULT_ERROR_MESSAGES: Record<HttpMethod, string> = {
  GET: "Failed to fetch data",
  POST: "Failed to create data",
  PUT: "Failed to update data",
  PATCH: "Failed to update data",
  DELETE: "Failed to delete data",
};

/** No response arrived at all — a network failure, a timeout, an abort. */
const TRANSPORT_FAILURE_STATUS = 0;

const HTTP_UNAUTHORIZED = 401;

/**
 * Whether the app-shell error handler already showed UI for this failure.
 *
 * It marks the statuses it owns (network, 401/403/429/5xx, a recognised 402);
 * a second toast on top of the login modal or the paywall would be noise.
 */
export const isHandled = (error: unknown): boolean =>
  (error as { handled?: boolean } | undefined)?.handled === true;

const requestIdOf = (headers: unknown): string | undefined => {
  const value = (headers as Record<string, unknown> | undefined)?.[
    REQUEST_ID_HEADER
  ];
  return typeof value === "string" ? value : undefined;
};

/** Convert any transport failure into the one error every consumer catches. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError(error) && error.response) {
    return ApiError.fromBody(error.response.status, error.response.data, {
      fallbackMessage: error.message,
      requestId: requestIdOf(error.response.headers),
      cause: error,
    });
  }
  const message = error instanceof Error ? error.message : String(error);
  return new ApiError(message, TRANSPORT_FAILURE_STATUS, { cause: error });
}

export function announceSuccess(options: ApiOptions): void {
  if (options.successMessage && !options.silent) {
    toast.success(options.successMessage);
  }
}

/**
 * Log, track and toast a failed request, then hand back the error to throw.
 *
 * A 401 is an expected state for anonymous visitors on public pages (which
 * never mount the error handler) — the app shell surfaces it with the login
 * modal, so it is never toasted as a generic failure.
 */
export function reportFailure(
  method: HttpMethod,
  url: string,
  error: ApiError,
  options: ApiOptions,
  handled: boolean,
): ApiError {
  console.error(`${method} ${url} failed:`, error);

  // Track failed requests in PostHog (client-only; analytics.ts is "use client").
  if (globalThis.window !== undefined) {
    trackEvent(ANALYTICS_EVENTS.API_REQUEST_FAILED, {
      method,
      // No PII to PostHog: the query string can carry search terms or tokens, and
      // the envelope's message can echo user input — the machine code cannot.
      url: url.split("?")[0],
      status: error.status,
      error_message:
        error.status === TRANSPORT_FAILURE_STATUS
          ? error.message
          : (error.code ?? `HTTP ${error.status}`),
    });
  }

  if (!options.silent && !handled && error.status !== HTTP_UNAUTHORIZED) {
    toast?.error?.(
      options.errorMessage ||
        error.envelope?.message ||
        DEFAULT_ERROR_MESSAGES[method],
    );
  }

  return error;
}
