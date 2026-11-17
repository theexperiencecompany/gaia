import type { StandalonePageBack } from "@/components/layout/StandalonePage";

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

export {
  BRIEFINGS_SETTINGS_PATH,
  POSTMARKS_SETTINGS_PATH,
} from "@shared/constants/routes";

/** A brief's own page leads back to the archive it is filed in. */
export const BACK_TO_BRIEFINGS: StandalonePageBack = {
  href: "/briefings",
  label: "Briefings",
};

/** Briefs the archive reads per page. */
export const BRIEFING_ARCHIVE_PAGE_SIZE = 30;
