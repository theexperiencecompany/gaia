/**
 * Reject webhook events whose `message.timestamp` is older than this many
 * milliseconds. Mitigates replay of captured signed payloads — a valid
 * signature alone is not enough if an attacker can resend the same body.
 */
export const REPLAY_WINDOW_MS = 5 * 60 * 1000;

/**
 * Re-emit cadence for the "typing…" indicator while a reply is being generated.
 *
 * Although the Cloud API documents a ~25s validity window, the WhatsApp *client*
 * only animates "typing…" for a few seconds per emit before it decays. A slow
 * cadence (8s/20s) therefore leaves visible gaps — the indicator decays, then
 * reappears on the next emit (the "comes, goes, comes back" flicker). We re-emit
 * faster than the client's decay so the animation stays continuous for the whole
 * generation; stop() cancels it the instant the reply is sent.
 */
export const TYPING_REFRESH_MS = 3 * 1000;

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
