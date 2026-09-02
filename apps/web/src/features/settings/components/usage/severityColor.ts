import {
  USAGE_DANGER_THRESHOLD,
  USAGE_WARN_THRESHOLD,
} from "@shared/constants/usage";
import { ACCENT, NEAR } from "./usageChrome";

const HIT = "#ff453a"; // vibrant red — limit reached; only severityColor picks it

/** Only the warning states borrow status hues; the "fine" state is the caller's
 * base color, so a glance separates fine / watch-out / maxed without a rainbow.
 * Thresholds are shared with mobile (see @shared/constants/usage). */
export function severityColor(percentage: number, base: string = ACCENT) {
  if (percentage >= USAGE_DANGER_THRESHOLD) return HIT;
  if (percentage >= USAGE_WARN_THRESHOLD) return NEAR;
  return base;
}
