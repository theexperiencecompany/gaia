import type { QuietHours } from "@shared/api/generated";

/**
 * The quiet-hours slider runs noon to noon, so a night window that crosses
 * midnight (22:00 to 08:00) is one unbroken range. Axis values are hours
 * from midnight of the first day: 12 is noon, 24 midnight, 36 the next noon.
 */
export const QUIET_AXIS_START = 12;
export const QUIET_AXIS_END = 36;
export const QUIET_AXIS_MARKS = [12, 18, 24, 30, 36] as const;

const HOURS_PER_DAY = 24;

/** Place a window on the noon-to-noon axis as [start, end]. */
export function toAxis({
  start_hour,
  end_hour,
}: Pick<QuietHours, "start_hour" | "end_hour">): [number, number] {
  const start =
    start_hour < QUIET_AXIS_START ? start_hour + HOURS_PER_DAY : start_hour;
  const end =
    end_hour <= QUIET_AXIS_START ? end_hour + HOURS_PER_DAY : end_hour;
  return [start, end];
}

/** Read a slider range back as clock hours, 0 to 23. */
export function fromAxis([start, end]: [number, number]): Pick<
  QuietHours,
  "start_hour" | "end_hour"
> {
  return {
    start_hour: start % HOURS_PER_DAY,
    end_hour: end % HOURS_PER_DAY,
  };
}

/** An hour of the day as the user's locale writes it, like "10 PM" or "22:00". */
export function formatHour(hour: number, locale?: string): string {
  const at = new Date(2000, 0, 1, hour % HOURS_PER_DAY);
  return new Intl.DateTimeFormat(locale, { hour: "numeric" }).format(at);
}
