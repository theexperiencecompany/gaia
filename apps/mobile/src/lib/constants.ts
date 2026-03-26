// Base URL (Origin) - e.g. http://localhost:8000
// Prioritize environment variable if set; fall back to localhost for
// development so that API_BASE_URL is never the string "undefined/api/v1".
export const API_ORIGIN =
  process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

// API V1 URL - e.g. http://localhost:8000/api/v1
export const API_BASE_URL = `${API_ORIGIN}/api/v1`;
