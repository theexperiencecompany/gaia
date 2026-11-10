import { formatDate } from "./dateUtils";

export interface RateLimitResetInfo {
  label: string;
  detail: string;
}

const MINUTES_PER_DAY = 24 * 60;

function availableAt(reset: Date): string {
  return `Available again at ${reset.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

/** When a limit lifts, worded for its distance: a countdown today, the day itself beyond that. */
export function rateLimitResetInfo(
  resetTime?: string,
): RateLimitResetInfo | null {
  if (!resetTime) return null;
  const reset = new Date(resetTime);
  const diffMs = reset.getTime() - Date.now();
  if (diffMs <= 0)
    return {
      label: "Resets very soon",
      detail: "Your limit will refresh shortly.",
    };
  const diffMins = Math.ceil(diffMs / 60000);
  // A monthly pause is days away: name the day instead of counting hours.
  if (diffMins > MINUTES_PER_DAY)
    return {
      label: `Resets on ${formatDate(reset)}`,
      detail: "Your allowance refreshes on your billing day.",
    };
  if (diffMins > 60) {
    const hours = Math.ceil(diffMins / 60);
    return {
      label: `Resets in ${hours} hour${hours !== 1 ? "s" : ""}`,
      detail: availableAt(reset),
    };
  }
  return {
    label: `Resets in ${diffMins} minute${diffMins !== 1 ? "s" : ""}`,
    detail: availableAt(reset),
  };
}
