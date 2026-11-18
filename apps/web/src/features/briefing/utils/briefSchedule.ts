/** What a briefing schedule means for when a brief lands, as the API reports it. */
import type { BriefingScheduleState } from "@gaia/shared/types";

/** The hour the daily brief actually lands when quiet hours hold it past its own, else null. */
export function quietHoursLanding(
  schedule: Pick<BriefingScheduleState, "hour" | "daily_brief_hour">,
): number | null {
  const lands = schedule.daily_brief_hour;
  return lands === null || lands === schedule.hour ? null : lands;
}
