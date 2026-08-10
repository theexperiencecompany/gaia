/**
 * Shared usage-severity thresholds, expressed as a percentage of an allowance.
 * Web and mobile both key their "healthy / near the limit / limit hit" states
 * off these so the two platforms never drift apart.
 */

/** At or above this percentage the UI warns the user they're nearing the limit. */
export const USAGE_WARN_THRESHOLD = 75;

/** At or above this percentage the allowance is treated as exhausted. */
export const USAGE_DANGER_THRESHOLD = 100;
