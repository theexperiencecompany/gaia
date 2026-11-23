import { SESSION_HINT_COOKIE } from "@shared/utils/sessionCookies";

const HINT_PREFIX = `${SESSION_HINT_COOKIE}=`;

/**
 * Whether the API marked this browser signed in. The session cookie itself is
 * HttpOnly and lives on the API's host, so this hint is all the web can read.
 */
export const hasSessionHint = (): boolean =>
  typeof document !== "undefined" &&
  document.cookie.split("; ").some((entry) => entry.startsWith(HINT_PREFIX));
