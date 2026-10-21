export const SESSION_RESUMED_KEY = "gaia_session_resumed_tracked";

/** Session cookies the API sets on sign-in: WorkOS, then local (self-host) auth. */
export const SESSION_COOKIES = ["wos_session", "gaia_session"] as const;

const AUTH_PAGES = ["/login", "/signup"];
export const PUBLIC_PAGES = [...AUTH_PAGES, "/terms", "/privacy", "/contact"];

/** The shortest password a local (self-host) account accepts; the API enforces the same. */
export const MIN_PASSWORD_LENGTH = 8;
