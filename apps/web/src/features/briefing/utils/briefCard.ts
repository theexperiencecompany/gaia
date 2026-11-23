/**
 * Every way a folded brief reaches the web (the archive, a postmark, the in-app
 * notification, GAIA's chat message) carries the API's one BriefCard; the folded
 * card shows it as the summary below.
 */
import type { BriefCard } from "@shared/api/generated";

import type { NotificationView } from "@/types/features/notificationTypes";

export type { BriefCard } from "@shared/api/generated";

/** What a folded brief shows before it is opened. */
export interface FoldedBriefSummary {
  headline: string;
  /** ISO day of the brief (YYYY-MM-DD). */
  date: string;
  kind: BriefCard["kind"];
  imageUrl: string | null;
  /** Share of the edition's height where its letter folds. */
  editionFold: number | null;
  /** The paper's box on its desk, [left, top, right, bottom] shares of the edition. */
  editionPaper: number[] | null;
  editionName: string | null;
  stampCityName: string | null;
  needsYouCount: number;
}

/** The brief's own page. */
export function briefPath(briefingId: string): string {
  return `/brief/${briefingId}`;
}

/** What the folded card shows, read off the brief's card. */
export function foldedBrief(card: BriefCard): FoldedBriefSummary {
  return {
    headline: card.headline,
    date: card.date,
    kind: card.kind,
    imageUrl: card.edition?.image_url ?? null,
    editionFold: card.edition?.fold ?? null,
    editionPaper: card.edition?.paper ?? null,
    editionName: card.edition_name,
    stampCityName: card.stamp_city_name,
    needsYouCount: card.needs_you_count,
  };
}

/** The brief card a briefing notification carries, or null for any other notification. */
export function notificationBrief(
  notification: NotificationView,
): BriefCard | null {
  const details = notification.details;
  return details?.kind === "briefing_daily" ||
    details?.kind === "briefing_weekly"
    ? details.card
    : null;
}
