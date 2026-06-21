/**
 * Reject webhook events whose `message.timestamp` is older than this many
 * milliseconds. Mitigates replay of captured signed payloads — a valid
 * signature alone is not enough if an attacker can resend the same body.
 */
export const REPLAY_WINDOW_MS = 5 * 60 * 1000;

/**
 * Approved utility template used to deliver proactive notifications when a
 * free-form send fails (e.g. the 24-hour window is closed). Single body
 * variable named `body`.
 */
export const NOTIFICATION_TEMPLATE_NAME = "gaia_notification";
export const NOTIFICATION_TEMPLATE_LANGUAGE = "en_US";
export const NOTIFICATION_TEMPLATE_PARAM_NAME = "body";

/**
 * Max length for the template body parameter. Meta caps the rendered body at
 * 1024 chars; staying well under leaves room for the template's fixed text.
 */
export const TEMPLATE_BODY_MAX_LENGTH = 900;
