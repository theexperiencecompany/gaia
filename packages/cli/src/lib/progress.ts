/**
 * How much of a long step is done, of how much: what every progress bar
 * shows beside its percentage, so a percentage never stands alone.
 * @module lib/progress
 */

import { formatByteProgress } from "./byte-size.js";
import { formatEta } from "./eta.js";

export interface ProgressAmount {
  done: number;
  total: number;
  unit: "bytes" | "services";
  /** The total still counts parts whose size is not known yet. */
  estimated: boolean;
}

/** What a step reports while it runs: its heading, one plain sub-line, and how far along it is. */
export interface StepProgress {
  label: string;
  detail?: string;
  amount?: ProgressAmount;
}

/** 0-100 for a bar: the given position, else done / total. */
export function progressPercent(
  amount: ProgressAmount,
  percent?: number,
): number {
  if (percent !== undefined) return percent;
  if (amount.total <= 0) return 0;
  return Math.min(100, Math.floor((amount.done / amount.total) * 100));
}

/** "62%  410 / 660 MB · about 1 min left", "7 / 9 services". */
export function progressCaption(
  amount: ProgressAmount,
  options: { percent?: number; etaMs?: number | null } = {},
): string {
  const size =
    amount.unit === "bytes"
      ? formatByteProgress(amount.done, amount.total, amount.estimated)
      : `${amount.done} / ${amount.total} services`;
  const eta =
    options.etaMs !== undefined && options.etaMs !== null
      ? ` · ${formatEta(options.etaMs)}`
      : "";
  return `${progressPercent(amount, options.percent)}%  ${size}${eta}`;
}
