import { z } from "zod";
import type { ConversationEntriesPage } from "../api/generated";
import { ScreenItemSchema } from "./entries";
import { StateFrameSchema } from "./frames";
import type { ConversationView } from "./types";

/** Entries asked for per page when a reader scrolls past the oldest item loaded. */
export const HISTORY_PAGE_SIZE = 50;

/** A page of the screen as a load, a sync or a page back returns it, with the head's state. */
export const ConversationPageSchema = z.object({
  items: z.array(ScreenItemSchema),
  state: StateFrameSchema,
  has_older: z.boolean(),
  cursor: z.number().int().min(1).nullable(),
}) satisfies z.ZodType<
  Pick<ConversationEntriesPage, "items" | "state" | "has_older" | "cursor">
>;

export type ConversationPage = z.infer<typeof ConversationPageSchema>;

/**
 * The seq the next older page is read before once page is taken into view; null when
 * nothing older exists. Items the view already held from before the page keep the
 * cursor it had.
 */
export function olderBefore(
  view: ConversationView,
  page: ConversationPage,
  held: number | null,
): number | null {
  const first = page.items[0]?.seq;
  if (first === undefined || (view.items[0]?.seq ?? first) < first) return held;
  return page.cursor;
}

export interface OlderHistorySource {
  /** The seq the next older page is read before; null once the first entry is held. */
  olderBefore: () => number | null;
  fetchPage: (beforeSeq: number, limit: number) => Promise<ConversationPage>;
  applyPage: (page: ConversationPage) => void | Promise<void>;
}

/**
 * Load the page before the oldest held entry, one request at a time.
 * A call while one is in flight joins it; nothing is fetched once nothing older exists.
 */
export const createOlderHistoryLoader = (
  source: OlderHistorySource,
): (() => Promise<void>) => {
  let inFlight: Promise<void> | null = null;
  return () => {
    if (inFlight) return inFlight;
    const beforeSeq = source.olderBefore();
    if (beforeSeq === null) return Promise.resolve();
    inFlight = source
      .fetchPage(beforeSeq, HISTORY_PAGE_SIZE)
      .then((page) => source.applyPage(page))
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  };
};
