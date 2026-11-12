/** Rows an edition prints per items block or calendar; the rest wait on the full brief page. Mirrors EDITION_ROWS_SHOWN in apps/api/app/constants/briefing.py. */
export const EDITION_ROWS_SHOWN = 3;

/**
 * What stopping a brief's link cannot take back: the edition image is a
 * permanent CDN URL already embedded in the brief's email.
 */
export const BRIEF_STOP_WARNING =
  "The edition image keeps its own address, which may already be in your email, so it stays viewable.";
