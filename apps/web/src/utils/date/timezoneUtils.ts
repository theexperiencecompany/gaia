import { toZonedTime } from "date-fns-tz";

/**
 * Gets the user's current timezone
 * @returns {string} Timezone identifier (e.g., "Asia/Kolkata", "America/New_York")
 */
const getUserTimezone = (): string => {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
};

/**
 * Determines time grouping (Today/Yesterday/Earlier) based on user's local timezone
 *
 * @param {string} createdAt - UTC timestamp string
 * @returns {"Today" | "Yesterday" | "Earlier"} Time group classification
 *
 * @example
 * // Server UTC: "2025-01-01T20:00:00.000000"
 * // User in IST: converts to 1:30 AM next day, returns "Today"
 * getTimeGroup("2025-01-01T20:00:00.000000")
 */
export const getTimeGroup = (
  createdAt: string,
): "Today" | "Yesterday" | "Earlier" => {
  const userTimeZone = getUserTimezone();

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
