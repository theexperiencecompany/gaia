/**
 * What a briefing schedule means for when a brief lands, read on the web.
 *
 * INTEGRATION(B1-12): BriefingScheduleState will carry has_daily_brief and the
 * effective hour (the daily brief's hour with quiet hours applied). Then
 * hasDailyBrief returns schedule.has_daily_brief, quietHoursLanding returns the
 * effective hour when it differs from schedule.hour, and isQuietHour and
 * DAILY_BRIEF_FREQUENCIES are deleted; their callers do not change.
 */
import type { BriefingScheduleState } from "@gaia/shared/types";
import type { QuietHours } from "@shared/api/generated";

/** Frequencies that send a daily brief; the weekly digest alone carries no workflow results. */
const DAILY_BRIEF_FREQUENCIES: ReadonlySet<BriefingScheduleState["frequency"]> =
  new Set(["daily", "weekdays"]);

/** Whether the schedule sends a daily brief, so its hour means something. */
export function hasDailyBrief(
  schedule: Pick<BriefingScheduleState, "frequency">,
): boolean {
  return DAILY_BRIEF_FREQUENCIES.has(schedule.frequency);
}

/** Whether an hour on the user's clock falls inside their quiet hours; the end hour is outside. */
function isQuietHour(hours: QuietHours, hour: number): boolean {
  if (!hours.enabled) return false;
  if (hours.start_hour < hours.end_hour) {
    return hours.start_hour <= hour && hour < hours.end_hour;
  }
  return hour >= hours.start_hour || hour < hours.end_hour;
}

/** The hour the daily brief actually lands when quiet hours hold it past its own, else null. */
export function quietHoursLanding(
  schedule: Pick<BriefingScheduleState, "frequency" | "hour">,
  quietHours: QuietHours,
): number | null {
  if (!hasDailyBrief(schedule) || schedule.hour === undefined) return null;
  return isQuietHour(quietHours, schedule.hour) ? quietHours.end_hour : null;
}
