/**
 * Every way a folded brief reaches the web, turned into the one summary its card shows.
 *
 * INTEGRATION(P-api1): the API will embed one generated BriefCard in BriefingView,
 * Postmark, the briefing notification's metadata and the chat message's tool data.
 * Then BriefCard below becomes a re-export of the generated type and each
 * source's adapter collapses to `foldedBrief(source.card)`; nothing else changes.
 */
import type {
  BriefingPayload,
  BriefingView,
  EditionImage,
  Postmark,
} from "@shared/api/generated";
import { z } from "zod";

import type { NotificationView } from "@/types/features/notificationTypes";

/** What a folded brief shows before it is opened. */
export interface FoldedBriefSummary {
  headline: string;
  /** ISO day of the brief (YYYY-MM-DD). */
  date?: string;
  kind?: "daily" | "weekly";
  lede?: string;
  imageUrl?: string | null;
  /** Share of the edition's height where its letter folds. */
  editionFold?: number | null;
  /** The paper's box on its desk, [left, top, right, bottom] shares of the edition. */
  editionPaper?: number[] | null;
  editionName?: string | null;
  stampCityName?: string | null;
  needsYouCount?: number | null;
}

/** A brief folded to its card, as GAIA's chat message and the in-app notification carry it (the API's BriefingCardData). */
export type BriefCard = Pick<
  BriefingView,
  | "date"
  | "kind"
  | "edition"
  | "edition_name"
  | "stamp_city_name"
  | "needs_you_count"
> & {
  briefing_id: BriefingView["id"];
  headline: BriefingPayload["headline"];
};

/** The brief's own page. */
export function briefPath(briefingId: string): string {
  return `/brief/${briefingId}`;
}

/** The edition's image and where it folds, as the folded card reads them; all null for a note. */
function editionLayout(
  edition: EditionImage | null,
): Pick<FoldedBriefSummary, "imageUrl" | "editionFold" | "editionPaper"> {
  return {
    imageUrl: edition?.image_url ?? null,
    editionFold: edition?.fold ?? null,
    editionPaper: edition?.paper ?? null,
  };
}

/** What the folded card shows, read off the brief's card. */
export function foldedBrief(card: BriefCard): FoldedBriefSummary {
  return {
    headline: card.headline,
    date: card.date,
    kind: card.kind,
    ...editionLayout(card.edition),
    editionName: card.edition_name,
    stampCityName: card.stamp_city_name,
    needsYouCount: card.needs_you_count,
  };
}

/** An archived brief's card. */
export function viewCard(view: BriefingView): BriefCard {
  return { ...view, briefing_id: view.id, headline: view.payload.headline };
}

/** The brief a stamp came on: its edition rides along so it can be readied before it is pressed. */
export function postmarkBrief(postmark: Postmark): FoldedBriefSummary {
  return {
    headline: `Your brief from ${postmark.city}`,
    ...editionLayout(postmark.edition),
  };
}

/** A brief GAIA's OpenUI component carries: its payload alone, with no stored brief behind it. */
export function payloadBrief(
  payload: Pick<BriefingPayload, "headline" | "date" | "lede">,
): FoldedBriefSummary {
  return { headline: payload.headline, date: payload.date, lede: payload.lede };
}

/** The weekly recap's notification kind (NOTIFICATION_KIND_BRIEFING_WEEKLY in the API). */
const NOTIFICATION_KIND_BRIEFING_WEEKLY = "briefing_weekly";

/** The card fields a briefing notification's metadata carries; its "kind" is the notification's own. */
const NotificationBriefSchema = z.object({
  briefing_id: z.string(),
  date: z.string(),
  kind: z.string(),
  edition: z
    .object({
      image_url: z.string(),
      fold: z.number().nullable(),
      paper: z.array(z.number()).nullable(),
    })
    .nullable(),
  edition_name: z.string().nullable(),
  stamp_city_name: z.string().nullable(),
  needs_you_count: z.number().int().nonnegative(),
}) satisfies z.ZodType<Omit<BriefCard, "kind" | "headline"> & { kind: string }>;

/** The brief a briefing notification carries, or null for any other notification. */
export function notificationBrief(
  notification: NotificationView,
): { briefingId: string; summary: FoldedBriefSummary } | null {
  const parsed = NotificationBriefSchema.safeParse(notification.metadata ?? {});
  if (!parsed.success) return null;
  const { kind, ...card } = parsed.data;
  return {
    briefingId: card.briefing_id,
    summary: foldedBrief({
      ...card,
      headline: notification.content.title,
      kind: kind === NOTIFICATION_KIND_BRIEFING_WEEKLY ? "weekly" : "daily",
    }),
  };
}
