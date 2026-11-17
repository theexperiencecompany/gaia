import type { StandalonePageBack } from "@/components/layout/StandalonePage";

/**
 * What stopping a brief's link cannot take back: the edition image is a
 * permanent CDN URL already embedded in the brief's email.
 */
export const BRIEF_STOP_WARNING =
  "The edition image keeps its own address, which may already be in your email, so it stays viewable.";

/** A brief's own page leads back to the archive it is filed in. */
export const BACK_TO_BRIEFINGS: StandalonePageBack = {
  href: "/briefings",
  label: "Briefings",
};

/** Briefs the archive reads per page. */
export const BRIEFING_ARCHIVE_PAGE_SIZE = 30;
