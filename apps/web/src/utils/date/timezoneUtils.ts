import { toZonedTime } from "date-fns-tz";
import { getBrowserTimezone } from "@/lib/timezone";

/**
 * Determines time grouping (Today/Yesterday/Earlier) based on the user's local timezone —
 * e.g. UTC 20:00 converts to 1:30 AM next day in IST, and returns "Today" for that day.
 */
export const getTimeGroup = (
  createdAt: string,
): "Today" | "Yesterday" | "Earlier" => {
  const userTimeZone = getBrowserTimezone();

  // Force the timestamp to be treated as UTC by adding 'Z' if it's missing
  const utcTimestamp = createdAt.endsWith("Z") ? createdAt : `${createdAt}Z`;
  const utcCreated = new Date(utcTimestamp);

  const now = new Date();
  const zonedCreated = toZonedTime(utcCreated, userTimeZone);
  const zonedNow = toZonedTime(now, userTimeZone);

  const diffInHours =
    (zonedNow.getTime() - zonedCreated.getTime()) / (1000 * 60 * 60);

  if (diffInHours < 24) return "Today";
  if (diffInHours < 48) return "Yesterday";
  return "Earlier";
};
