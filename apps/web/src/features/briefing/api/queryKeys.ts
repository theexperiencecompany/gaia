/** Canonical React Query keys for the user's briefs and their settings. */
export const briefingKeys = {
  /** Prefix: every brief read. */
  all: ["briefings"] as const,
  /** The archive, a page at a time. */
  archive: ["briefings", "archive"] as const,
  /** One brief; reading it marks it opened. */
  detail: (briefingId: string) => ["briefings", "detail", briefingId] as const,
  /** The collected Air Mail stamps. */
  postmarks: ["briefings", "postmarks"] as const,
  /** How often briefs come and the daily brief's hour. */
  schedule: ["briefings", "schedule"] as const,
  /** Which daily editions the brief draws. */
  editions: ["briefings", "editions"] as const,
};

/** A brief and its settings change at most a few times a day; reads stay fresh this long. */
export const BRIEFING_STALE_MS = 5 * 60 * 1000;
