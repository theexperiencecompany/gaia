/**
 * After an OAuth connect the backend finishes the heavy MCP work (handshake +
 * tools/list + indexing) in the background, so the integration's tools land a
 * few seconds after the redirect. The integrations page polls until they
 * appear instead of forcing the user to reload the page.
 */
export const POST_CONNECT_POLL_INTERVAL_MS = 2000;
export const POST_CONNECT_POLL_MAX_ATTEMPTS = 15;

/**
 * Why a bot connect link bounced to /integrations (`?connect_error=`), keyed by
 * the reasons `_connect_link_error` in the API's integrations config routes sends.
 */
export const CONNECT_LINK_ERROR_MESSAGES = {
  invalid_or_expired_link:
    "That connect link has expired or was already used. Ask GAIA for a new one.",
  could_not_start:
    "Couldn't start that connection. Ask GAIA for a new link and try again.",
} as const;

/**
 * Carries a bot connect link's code from /connect/<code> to the /connect page,
 * so the live code never sits in a page URL that analytics and replay record.
 * Lives as long as the code itself (CONNECT_LINK_TTL_MINUTES in the API).
 */
export const CONNECT_LINK_COOKIE = "gaia_connect_code";
export const CONNECT_LINK_COOKIE_MAX_AGE_SECONDS = 60 * 60;
export const CONNECT_LINK_PATH = "/connect";
