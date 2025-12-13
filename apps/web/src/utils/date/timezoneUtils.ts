import { formatDistanceToNow } from "date-fns";
import { toZonedTime } from "date-fns-tz";

/**
 * Gets the user's current timezone
 * @returns {string} Timezone identifier (e.g., "Asia/Kolkata", "America/New_York")
 */
export const getUserTimezone = (): string => {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
};

/**
 * Formats a UTC timestamp to show relative time in the user's local timezone
 *
 * @param {string} timestamp - UTC timestamp string (with or without 'Z' suffix)
 * @returns {string} Relative time string (e.g., "2 hours ago", "5 minutes ago")
 *
 * @example
 * // Server sends: "2025-01-01T12:00:00.000000" (UTC)
 * // User in IST timezone: returns "2 hours ago" (calculated from 5:30 PM IST)
 * formatTimestampWithTimezone("2025-01-01T12:00:00.000000")
 */
export const formatTimestampWithTimezone = (timestamp: string): string => {
  const userTimeZone = getUserTimezone(); // e.g., Asia/Kolkata

  // Force the timestamp to be treated as UTC by adding 'Z' if it's missing
  const utcTimestamp = timestamp.endsWith("Z") ? timestamp : `${timestamp}Z`;
  const utcDate = new Date(utcTimestamp); // Now correctly parsed as UTC

  const zonedDate = toZonedTime(utcDate, userTimeZone); // Convert UTC to user's local time (adds +5:30 for IST)

  // Show relative time based on your LOCAL timezone (e.g., "6 hours ago" in IST)
  const relativeTime = formatDistanceToNow(zonedDate, { addSuffix: true });

  return relativeTime;
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

/**
 * Converts UTC timestamp to user's local timezone Date object
 *
 * @param {string} timestamp - UTC timestamp string
 * @returns {Date} Date object in user's local timezone
 *
 * @example
 * // Server UTC: "2025-01-01T12:00:00.000000"
 * // User in IST: returns Date object representing 5:30 PM IST
 * convertToUserTimezone("2025-01-01T12:00:00.000000")
 */
export const convertToUserTimezone = (timestamp: string): Date => {
  const userTimeZone = getUserTimezone();
  const utcTimestamp = timestamp.endsWith("Z") ? timestamp : `${timestamp}Z`;
  const utcDate = new Date(utcTimestamp);

  return toZonedTime(utcDate, userTimeZone);
};
