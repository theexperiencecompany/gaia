import type { StandalonePageBack } from "@/components/layout/StandalonePage";

/** A brief's own page leads back to the archive it is filed in. */
export const BACK_TO_BRIEFINGS: StandalonePageBack = {
  href: "/briefings",
  label: "Briefings",
};

/** Briefs the archive reads per page. */
export const BRIEFING_ARCHIVE_PAGE_SIZE = 30;
