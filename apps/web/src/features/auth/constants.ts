export const SESSION_RESUMED_KEY = "gaia_session_resumed_tracked";

const AUTH_PAGES = ["/login", "/signup"];
export const PUBLIC_PAGES = [...AUTH_PAGES, "/terms", "/privacy", "/contact"];

// Phases where the user must stay in onboarding; the routing layer must not redirect into the main app.
export const ONBOARDING_PROCESSING_PHASES: ReadonlySet<string> = new Set([
  "personalization_pending",
  "personalization_complete",
  "getting_started",
]);
