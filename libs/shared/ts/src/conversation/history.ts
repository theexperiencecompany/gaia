import { z } from "zod";
import type { ConversationEntriesPage } from "../api/generated";
import { EntrySchema } from "./entries";
import { FRAME_KIND, StateFrameSchema } from "./frames";
import type { ConversationFrame, ConversationView } from "./types";
import { applyFrame } from "./view";

/** Entries asked for per page when a reader scrolls past the oldest one loaded. */
export const HISTORY_PAGE_SIZE = 50;

const LoggedEntrySchema = z.object({
  seq: z.number().int().min(1),
  at: z.iso.datetime({ offset: true }),
  entry: EntrySchema,
});

/** A page of the log as a load, a sync or a page back returns it: the stream's own entries and the head's state. */
export const ConversationPageSchema = z.object({
  entries: z.array(LoggedEntrySchema),
  state: StateFrameSchema,
  has_older: z.boolean(),
  cursor: z.number().int().min(1).nullable(),
}) satisfies z.ZodType<ConversationEntriesPage>;

export type ConversationPage = z.infer<typeof ConversationPageSchema>;

/**
 * Fold a page into the view through the reducer, as the stream would have: each entry
 * as its entry frame (a held seq changes only to a newer revision), then the state.
 */
export function hydrate(
  view: ConversationView,
  page: ConversationPage,
): ConversationView {
  const frames: ConversationFrame[] = [
    ...page.entries.map(
      (logged): ConversationFrame => ({ kind: FRAME_KIND.ENTRY, ...logged }),
    ),
    page.state,
  ];
  return frames.reduce((current, frame) => {
    const outcome = applyFrame(current, frame);
    // Entry and state frames always apply; only deltas and in-place updates can gap.
    if (outcome.status !== "applied")
      throw new Error(`a page frame did not apply: ${outcome.status}`);
    return outcome.view;
  }, view);
}

/**
 * The seq the next older page is read before once page is folded into view; null when
 * nothing older exists. Entries the view already held from before the page keep the
 * cursor it had.
 */
export function olderBefore(
  view: ConversationView,
  page: ConversationPage,
  held: number | null,
): number | null {
  const first = page.entries[0]?.seq;
  if (first === undefined || (view.entries[0]?.seq ?? first) < first)
    return held;
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
