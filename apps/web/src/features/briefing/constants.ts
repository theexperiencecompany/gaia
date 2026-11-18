import type { BriefPoolItem } from "@shared/api/generated";

import type { StandalonePageBack } from "@/components/layout/StandalonePage";

/** Rows an edition prints per items block or calendar; the rest wait on the full brief page. Mirrors EDITION_ROWS_SHOWN in apps/api/app/constants/briefing.py. */
export const EDITION_ROWS_SHOWN = 3;

/**
 * What stopping a brief's link cannot take back: the edition image is a
 * permanent CDN URL already embedded in the brief's email.
 */
export const BRIEF_STOP_WARNING =
  "The edition image keeps its own address, which may already be in your email, so it stays viewable.";

/** An opened brief or edition sample is drawn this wide, the screen's width less a gutter when narrower. */
export const BRIEF_LETTER_MAX_WIDTH_PX = 760;
export const LETTER_VIEWPORT_GUTTER_PX = 24;
export const BRIEF_LETTER_WIDTH = `min(${BRIEF_LETTER_MAX_WIDTH_PX}px, calc(100vw - ${LETTER_VIEWPORT_GUTTER_PX}px))`;

/** Where the reader sets how often briefs come and which editions they draw. */
export const BRIEFINGS_SETTINGS_PATH = "/settings/briefings";

/** The stamp album. Mirrors POSTMARKS_PATH in apps/api/app/constants/briefing.py. */
export const POSTMARKS_SETTINGS_PATH = "/settings/postmarks";

/** A brief's own page leads back to the archive it is filed in. */
export const BACK_TO_BRIEFINGS: StandalonePageBack = {
  href: "/briefings",
  label: "Briefings",
};

/** Where a brief item stands, in a few words. Mirrors ItemState's labels in apps/api/app/models/brief_item_models.py. */
export const BRIEF_ITEM_STATES: Record<BriefPoolItem["kind"], string> = {
  you: "Waiting on you",
  gaia: "In progress",
  lookback: "Done",
  failed: "Failed",
  note: "Note",
};

/** Briefs the archive reads per page. */
export const BRIEFING_ARCHIVE_PAGE_SIZE = 30;
