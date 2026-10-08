/**
 * What happens to the user when a request succeeds or fails.
 *
 * One place, shared by the path-typed client (./typed) and the URL-string
 * `apiService` (./service), so both toast the same way and both throw the one
 * `ApiError` with the backend's envelope already narrowed.
 */

import { ApiError, REQUEST_ID_HEADER } from "@shared/api";
import { SUBSCRIPTION_REQUIRED_CODE } from "@shared/types/subscription";
import axios, { AxiosError } from "axios";
import { track } from "@/lib/analytics";
import { API_ERROR_CODES } from "@/lib/api/errorCodes";
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

export const HTTP_UNAUTHORIZED = 401;
const HTTP_PAYMENT_REQUIRED = 402;

/** One api:request_failed per method, url, status and code per tab in this window: a retry loop is a rate, not a flood. */
const REQUEST_FAILED_DEDUPE_WINDOW_MS = 10 * 60 * 1000;

/** The fixed codes a transport failure is reported under; its message is free text and never leaves the browser. */
const TRANSPORT_FAILURE_CODES: Readonly<Record<string, string>> = {
  [AxiosError.ERR_NETWORK]: "network",
  [AxiosError.ECONNABORTED]: "timeout",
  [AxiosError.ETIMEDOUT]: "timeout",
  [AxiosError.ERR_CANCELED]: "aborted",
};
const UNKNOWN_TRANSPORT_FAILURE_CODE = "unknown";

const lastRequestFailureAt = new Map<string, number>();

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

/**
 * The states the app expects rather than suffers: a logged-out visitor's 401
 * (the same check the interceptor uses to open the login modal) and the
 * paywall's 402, which the server already records as paywall:blocked.
 */
const isExpectedState = (error: ApiError): boolean =>
  (error.status === HTTP_UNAUTHORIZED &&
    error.code === API_ERROR_CODES.NOT_AUTHENTICATED) ||
  (error.status === HTTP_PAYMENT_REQUIRED &&
    error.code === SUBSCRIPTION_REQUIRED_CODE);

/** The envelope's machine code, or for a request that got no response, a fixed transport code. */
const failureCode = (error: ApiError): string | undefined => {
  if (error.status !== TRANSPORT_FAILURE_STATUS) return error.code;
  const axiosCode =
    error.cause instanceof AxiosError ? error.cause.code : undefined;
  return (
    (axiosCode && TRANSPORT_FAILURE_CODES[axiosCode]) ??
    UNKNOWN_TRANSPORT_FAILURE_CODE
  );
};

function trackRequestFailure(
  method: HttpMethod,
  url: string,
  error: ApiError,
): void {
  if (isExpectedState(error)) return;
  // No PII to PostHog: the query string can carry search terms or tokens, and
  // the envelope's message can echo user input; the machine code cannot.
  const path = url.split("?")[0];
  const code = failureCode(error);
  const key = `${method} ${path} ${error.status} ${code}`;
  const now = Date.now();
  const last = lastRequestFailureAt.get(key);
  if (last !== undefined && now - last < REQUEST_FAILED_DEDUPE_WINDOW_MS) {
    return;
  }
  lastRequestFailureAt.set(key, now);
  track("api:request_failed", {
    method,
    url: path,
    status: error.status,
    error_code: code,
  });
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
    trackRequestFailure(method, url, error);
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
