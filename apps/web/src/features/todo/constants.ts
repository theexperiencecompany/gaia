/**
 * Bookkeeping labels the backend may carry on older GAIA todos. They are never
 * surfaced as user-facing chips or nav entries — the "Created by GAIA" badge and
 * the execution-status chip already convey everything they encoded, so showing
 * them would be redundant noise.
 */
export const INTERNAL_LABELS = new Set(["gaia-tracked", "failed"]);
