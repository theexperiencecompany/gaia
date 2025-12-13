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
 * Global axios timeout configuration
 * Set to 5 minutes to handle long-running requests
 */
axios.defaults.timeout = 300_000;

/**
 * Get the current user's timezone
 * Safely handles both client and server environments
 */
function getUserTimezone(): string {
  if (typeof window !== "undefined") {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch (error) {
      console.warn("Failed to detect timezone, using UTC as fallback:", error);
      return "UTC";
    }
  }
  // Default to UTC on server-side
  return "UTC";
}

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
