/**
 * How much of a long step is done, of how much: what every progress bar
 * shows beside its percentage, so a percentage never stands alone.
 * @module lib/progress
 */

import { formatByteProgress } from "./byte-size.js";
import { formatEta } from "./eta.js";
import { formatElapsed } from "./run-steps.js";

/** Bytes that haven't moved for this long are said to have stalled. */
const STALL_AFTER_MS = 20_000;

export interface ProgressAmount {
  done: number;
  total: number;
  unit: "bytes" | "services";
  /** The total still counts parts whose size is not known yet. */
  estimated: boolean;
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

/** "no data for 34s, still trying" once amountMovedAt is STALL_AFTER_MS old, else null. */
export function stallNote(
  amountMovedAt: number | undefined,
  now: number,
): string | null {
  if (amountMovedAt === undefined) return null;
  const stalledMs = now - amountMovedAt;
  if (stalledMs < STALL_AFTER_MS) return null;
  return `no data for ${formatElapsed(stalledMs)}, still trying`;
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
