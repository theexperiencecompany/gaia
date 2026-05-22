export const SESSION_RESUMED_KEY = "gaia_session_resumed_tracked";

export const AUTH_PAGES = ["/login", "/signup"];
export const PUBLIC_PAGES = [...AUTH_PAGES, "/terms", "/privacy", "/contact"];

/**
 * Onboarding phases during which the user must stay in the onboarding flow.
 * While the phase is one of these, the personalization pipeline / getting-
 * started experience is still running, so the routing layer must not send the
 * user into the main app. Shared by `useFetchUser` and `useOnboardingGuard` so
 * both agree on what "still onboarding" means — a mismatch (one treating
 * `getting_started` as done while the other treated it as in-progress) caused
 * redirect fights between /onboarding and /c.
 */
export const ONBOARDING_PROCESSING_PHASES: ReadonlySet<string> = new Set([
  "personalization_pending",
  "personalization_complete",
  "getting_started",
]);
