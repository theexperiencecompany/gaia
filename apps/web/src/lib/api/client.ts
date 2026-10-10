import { getUserTimezone } from "@shared/api/timezone";
import type { AxiosError, InternalAxiosRequestConfig } from "axios";
import axios from "axios";
import { toApiOrigin } from "./origin";

/**
 * API Client Configuration
 *
 * The one axios instance every request in the app goes through — directly for
 * the URL-string `apiService`, and as the transport under the path-typed
 * client in ./typed. Nothing outside lib/api imports the instance: error UI
 * registers through `registerApiErrorHandler`, and the SSE helpers read their
 * URL and headers from `apiBaseUrl` / `clientHeaders` here.
 */

// Validate required environment variables
if (!process.env.NEXT_PUBLIC_API_BASE_URL) {
  throw new Error(
    "Missing required environment variable: NEXT_PUBLIC_API_BASE_URL",
  );
}

/**
 * Global axios timeout configuration. Defaults to 5 minutes to handle
 * long-running requests; override with API_TIMEOUT_MS — a server-only,
 * build-time var used to fail fast when the API is slow/unreachable during
 * generateStaticParams. Only a finite, positive override is honored (so a
 * malformed, negative, or Infinity value can't disable timeouts for every
 * request); on the client the var is undefined and the default applies.
 */
const DEFAULT_API_TIMEOUT_MS = 300_000;
const parsedApiTimeoutMs = Number(process.env.API_TIMEOUT_MS);
axios.defaults.timeout =
  Number.isFinite(parsedApiTimeoutMs) && parsedApiTimeoutMs > 0
    ? parsedApiTimeoutMs
    : DEFAULT_API_TIMEOUT_MS;

/** The configured base, without a trailing slash: `https://api.…/api/v1`. */
export const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL.replace(
  /\/+$/,
  "",
);

/** The server root the generated `paths` hang off (see toApiOrigin). */
export const apiOrigin = toApiOrigin(apiBaseUrl);

/** The headers every request carries, for callers that cannot use axios. */
export const clientHeaders = (): Record<string, string> => ({
  "x-timezone": getUserTimezone(),
});

/**
 * Authenticated axios instance for API calls.
 * Includes credentials (cookies) for authentication.
 */
export const apiauth = axios.create({
  baseURL: apiBaseUrl,
  withCredentials: true,
  headers: clientHeaders(),
});

// Keep the timezone header current even if it changes during the session.
const updateTimezoneHeader = (config: InternalAxiosRequestConfig) => {
  config.headers["x-timezone"] = getUserTimezone();

  return config;
};

apiauth.interceptors.request.use(updateTimezoneHeader);

/** Surfaces API error UI (login modal, paywall, rate-limit toasts). */
export type ApiErrorHandler = (
  error: AxiosError & { handled?: boolean },
) => void;

/**
 * Mount the app shell's error UI on every response.
 *
 * Returns the eject function; only the (main) provider tree registers one, so
 * landing pages never surface background-fetch toasts to anonymous visitors.
 */
export function registerApiErrorHandler(handle: ApiErrorHandler): () => void {
  const interceptor = apiauth.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      handle(error);
      return Promise.reject(error);
    },
  );
  return () => {
    apiauth.interceptors.response.eject(interceptor);
  };
}
