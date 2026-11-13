/**
 * How long the integrations page shows "Setting up tools" after a connect when
 * the tools never arrive: the backend sends no event when background discovery
 * fails, so the wait is bounded instead.
 */
export const POST_CONNECT_SETTLE_TIMEOUT_MS = 30_000;

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

/**
 * What a finished sign-in did to the user's accounts, sent by the API's Composio
 * callback as `?account_outcome=` (AccountConnectOutcome in the API).
 */
export const ACCOUNT_OUTCOME_PARAM = "account_outcome";
export const AccountOutcome = {
  RECONNECTED: "reconnected",
  ALREADY_CONNECTED: "already_connected",
} as const;
