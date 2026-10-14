// Base URL (Origin) - e.g. http://localhost:8000
// Prioritize environment variable if set; fall back to localhost for
// development so that API_BASE_URL is never the string "undefined/api/v1".
export const API_ORIGIN =
  process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

// API V1 URL - e.g. http://localhost:8000/api/v1
export const API_BASE_URL = `${API_ORIGIN}/api/v1`;

// Marketing pricing page — where a non-subscribed user goes when the backend
// minted no personal checkout link. The rest of the app links to heygaia.io.
export const PRICING_URL = "https://heygaia.io/pricing";
