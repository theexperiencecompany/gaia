/** Messages asked for per page when a reader scrolls past the oldest one loaded. */
export const HISTORY_PAGE_SIZE = 50;

/** One page of saved messages before a seq, oldest first; has_more when older ones remain. */
export interface HistoryPage<M> {
  messages: M[];
  has_more: boolean;
}

// Below every server seq (they start at 1).
const UNPLACED_SEQ = 0;

interface Sequenced {
  seq?: number | null;
}

/** The seq of the oldest message that has one: the cursor the previous page is read before. */
export const oldestSeq = (messages: readonly Sequenced[]): number | null =>
  messages.reduce<number | null>(
    (oldest, message) =>
      message.seq == null || (oldest !== null && oldest <= message.seq)
        ? oldest
        : message.seq,
    null,
  );

/** The newest page as fetched, after the older messages already loaded before it. */
export const withNewestPage = <M extends Sequenced>(
  loaded: readonly M[],
  newest: readonly M[],
): M[] => {
  const boundary = oldestSeq(newest);
  if (boundary === null) return [...newest];
  const older = loaded.filter(
    (message) => message.seq != null && message.seq < boundary,
  );
  return [...older, ...newest];
};

export interface OlderHistorySource<M> {
  /** The server said older messages remain before the oldest one loaded. */
  hasOlder: () => boolean;
  oldestLoadedSeq: () => number | null;
  fetchPage: (beforeSeq: number, limit: number) => Promise<HistoryPage<M>>;
  /** Prepend the page and record its has_more as the new hasOlder. */
  applyPage: (page: HistoryPage<M>) => void | Promise<void>;
}

/**
 * Load the page before the oldest loaded message, one request at a time.
 * A call while one is in flight joins it; nothing is fetched once hasOlder is false.
 */
export const createOlderHistoryLoader = <M>(
  source: OlderHistorySource<M>,
): (() => Promise<void>) => {
  let inFlight: Promise<void> | null = null;
  return () => {
    if (inFlight) return inFlight;
    const beforeSeq = source.oldestLoadedSeq();
    if (!source.hasOlder() || beforeSeq === null) return Promise.resolve();
    inFlight = source
      .fetchPage(beforeSeq, HISTORY_PAGE_SIZE)
      .then((page) => source.applyPage(page))
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  };
};

/**
 * The chat screen's rows: saved history and the live view, one row per message id.
 * The server's history and its events project the same log under the same ids, so a
 * live row replaces the saved row it shares an id with (a row with no id is never
 * matched). Rows read in seq order; live
 * rows the server has not placed yet (a streaming draft, a pending send) come last.
 */
export const withLiveRows = <M extends Sequenced>(
  saved: readonly M[],
  live: readonly M[],
  idOf: (row: M) => string | undefined,
): M[] => {
  if (live.length === 0) return [...saved];
  const liveIds = new Set(live.map(idOf));
  const placed = [
    ...saved.filter((row) => {
      const id = idOf(row);
      return id === undefined || !liveIds.has(id);
    }),
    ...live.filter((row) => row.seq != null),
  ];
  // Saved rows cached before seq existed keep their place ahead of every placed row.
  placed.sort((a, b) => (a.seq ?? UNPLACED_SEQ) - (b.seq ?? UNPLACED_SEQ));
  return [...placed, ...live.filter((row) => row.seq == null)];
};
