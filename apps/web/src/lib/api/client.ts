import { getUserTimezone } from "@shared/api/timezone";
import axios, { type InternalAxiosRequestConfig } from "axios";

/**
 * API Client Configuration
 *
 * This module sets up axios instances for API communication with the backend.
 * It provides two main clients:
 * - api: Basic client with caching for public endpoints
 * - apiauth: Authenticated client with credentials for protected endpoints
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

/**
 * Base axios instance for public API calls
 * Used for endpoints that don't require authentication
 */
const baseInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL,
  headers: {
    "x-timezone": getUserTimezone(),
  },
});

/**
 * Authenticated axios instance for protected API calls
 * Includes credentials (cookies) for authentication
 * Used for endpoints that require user authentication
 */
export const apiauth = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_BASE_URL,
  withCredentials: true,
  headers: {
    "x-timezone": getUserTimezone(),
  },
});

// Add request interceptor to dynamically update timezone header
// This ensures the timezone is current even if it changes during the session
const updateTimezoneHeader = (config: InternalAxiosRequestConfig) => {
  // Always set the current timezone
  config.headers["x-timezone"] = getUserTimezone();

  return config;
};

// Apply the interceptor to both instances
baseInstance.interceptors.request.use(updateTimezoneHeader);
apiauth.interceptors.request.use(updateTimezoneHeader);

/**
 * API client for public endpoints - NO CACHING
 * Direct access to the base instance without caching
 */
export const api = baseInstance;
