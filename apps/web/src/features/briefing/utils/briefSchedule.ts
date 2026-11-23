/** What a briefing schedule means for when a brief lands, as the API reports it. */
import type { BriefingScheduleState } from "@gaia/shared/types";

/** The local "HH:MM:SS" the daily brief lands at when quiet hours hold it past its own hour, else null. */
export function quietHoursLanding(
  schedule: Pick<BriefingScheduleState, "hour" | "daily_brief_lands_at">,
): string | null {
  const lands = schedule.daily_brief_lands_at;
  return lands === null || Number(lands.split(":")[0]) === schedule.hour
    ? null
    : lands;
}
