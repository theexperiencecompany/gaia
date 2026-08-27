/**
 * Calendar date formatting utilities.
 *
 * The implementation lives in `@gaia/shared` (tool-utils/calendar-date-utils)
 * so web and mobile render identical calendar card dates. This module is a
 * compatibility shim — import from `@gaia/shared` in new code.
 */
export {
  bucketDate,
  formatAllDayDate,
  formatAllDayDateRange,
  formatDateWithRelative,
  formatTimedEventDate,
  formatTimeRange,
  formatTimeString,
  getEventDurationText,
  isDateOnly,
} from "@gaia/shared";
