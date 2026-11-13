/**
 * Reject webhook events whose `message.timestamp` is older than this many
 * milliseconds. Mitigates replay of captured signed payloads — a valid
 * signature alone is not enough if an attacker can resend the same body.
 */
export const REPLAY_WINDOW_MS = 5 * 60 * 1000;

/**
 * Re-emit cadence for the "typing…" indicator while a reply generates. The
 * Cloud API window is ~25s, but the client only animates a few seconds per
 * emit before decaying — too slow a cadence flickers. Re-emitting faster than
 * the client's decay keeps it continuous; `stop()` cancels it once sent.
 */
export const TYPING_REFRESH_MS = 3 * 1000;

/**
 * Approved utility template every message outside the customer-service window
 * goes out as. Single body variable named `body`.
 */
export const NOTIFICATION_TEMPLATE_NAME = "gaia_notification";
export const NOTIFICATION_TEMPLATE_LANGUAGE = "en_US";
export const NOTIFICATION_TEMPLATE_PARAM_NAME = "body";

/**
 * Max length for the template body parameter. Meta caps the rendered body at
 * 1024 chars; staying well under leaves room for the template's fixed text.
 */
export const TEMPLATE_BODY_MAX_LENGTH = 900;

/**
 * Meta's customer-service window: a business may send free-form messages only
 * this long after the user last wrote. Past it Meta accepts the send and fails it
 * later (error 131047), so the window is checked before sending, never after.
 */
export const CUSTOMER_SERVICE_WINDOW_MS = 24 * 60 * 60 * 1000;

/** Treat the window as closed this much early, for clock skew and send latency. */
export const CUSTOMER_SERVICE_WINDOW_MARGIN_MS = 5 * 60 * 1000;

/** Cap on reading a failed message's error from Kapso before the webhook answers. */
export const MESSAGE_STATUS_LOOKUP_TIMEOUT_MS = 5_000;
