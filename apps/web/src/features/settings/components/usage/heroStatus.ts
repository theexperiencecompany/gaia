import { USAGE_WARN_THRESHOLD } from "@shared/constants/usage";
import { formatDate } from "@shared/utils";

export type Period = "day" | "month";

export interface HeroStatus {
  headline: string;
  /** What the number means for the user right now, always with when it resets. */
  detail: string;
}

/** Local wall-clock time of an instant, e.g. "5:30 AM" — "midnight" would be
 * a lie for every user outside UTC. */
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function resetPhrase(win: Period, resetIso: string): string {
  return win === "day"
    ? `at ${fmtTime(resetIso)}`
    : formatDate(resetIso, "short");
}

/**
 * Copy for the usage hero, by window and how full it is.
 *
 * Both windows bind the same way: at 100% chat, workflows and tracked todos
 * pause until the window resets, so the copy names that moment up front.
 */
export function heroStatus(
  win: Period,
  percent: number,
  resetIso: string | undefined,
): HeroStatus {
  const allowance = win === "day" ? "daily allowance" : "monthly allowance";
  if (!resetIso) {
    return { headline: `of your ${allowance} used`, detail: "" };
  }
  const when = resetPhrase(win, resetIso);
  if (win === "month") {
    if (percent >= 100) {
      return {
        headline: `Paused until ${when}`,
        detail: `You've used this month's allowance. Chat, workflows and tracked todos resume ${when}, when it resets.`,
      };
    }
    if (percent >= USAGE_WARN_THRESHOLD) {
      return {
        headline: `of your ${allowance} used`,
        detail: `At 100%, chat, workflows and tracked todos pause until ${when}.`,
      };
    }
    return { headline: `of your ${allowance} used`, detail: `Resets ${when}` };
  }
  if (percent >= 100) {
    return {
      headline: "Today's limit reached",
      detail: `Chat and workflow runs pause until ${when}. Your conversations, workflows and settings are untouched.`,
    };
  }
  if (percent >= USAGE_WARN_THRESHOLD) {
    return {
      headline: `of your ${allowance} used`,
      detail: `At 100%, chat and workflow runs pause until ${when}.`,
    };
  }
  return { headline: `of your ${allowance} used`, detail: `Resets ${when}` };
}
