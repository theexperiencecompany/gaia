import {
  formatTimeRange,
  formatTimeString,
  isDateOnly,
} from "../../../tool-utils/calendar-date-utils";
import { formatDateUTC } from "../../../utils/dateUtils";

const ALL_DAY_LABEL = "All day";
/** `YYYY-MM-DD`, the calendar day at the head of every event time. */
const ISO_DATE_LENGTH = 10;
const UTC_OFFSET_SUFFIX = /(Z|[+-]\d{2}:\d{2})$/;

/**
 * The wall-clock time the event was booked at. Google sends it with the
 * calendar's offset; dropping the offset keeps a 10 AM meeting at 10 AM
 * whatever timezone the bot server runs in.
 */
function wallClock(dateTime: string): string {
  return dateTime.replace(UTC_OFFSET_SUFFIX, "");
}

/** "Thu, Nov 12": the event's own calendar day, read straight off its date. */
export function eventDayLabel(start: string | undefined): string | undefined {
  if (!start) return undefined;
  const day = start.slice(0, ISO_DATE_LENGTH);
  if (Number.isNaN(Date.parse(day))) return undefined;
  return formatDateUTC(day, "weekday");
}

/** "10 to 11 AM", or "All day" for an event that has a date but no time. */
export function eventTimeLabel(
  start: string | undefined,
  end: string | undefined,
): string | undefined {
  if (!start) return undefined;
  if (isDateOnly(start)) return ALL_DAY_LABEL;
  if (end) return formatTimeRange(wallClock(start), wallClock(end));
  const startTime = new Date(wallClock(start));
  return Number.isNaN(startTime.getTime())
    ? undefined
    : formatTimeString(startTime);
}
