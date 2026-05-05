/**
 * Reject webhook events whose `message.timestamp` is older than this many
 * milliseconds. Mitigates replay of captured signed payloads — a valid
 * signature alone is not enough if an attacker can resend the same body.
 */
export const REPLAY_WINDOW_MS = 5 * 60 * 1000;
