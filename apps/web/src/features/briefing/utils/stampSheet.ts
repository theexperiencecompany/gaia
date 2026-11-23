/** The blanks after the collected stamps: how many cells, and how many cities the last one stands for. */
export interface StampSheet {
  blanks: number;
  /** Cities the last blank counts, shown as "+N"; null when each blank is one city. */
  lastCounts: number | null;
}

/**
 * Blanks only to finish the row the collected stamps end on, or one full row
 * when they end flush, never a partial row past that; the last blank carries
 * every city the sheet leaves out so the cells add up to the total.
 */
export function stampSheet(
  collected: number,
  total: number,
  columns: number,
): StampSheet {
  const remaining = Math.max(total - collected, 0);
  const openInRow = columns - (collected % columns);
  const blanks = Math.min(remaining, openInRow);
  const lastCounts = remaining - (blanks - 1);
  return {
    blanks,
    lastCounts: blanks > 0 && lastCounts > 1 ? lastCounts : null,
  };
}
