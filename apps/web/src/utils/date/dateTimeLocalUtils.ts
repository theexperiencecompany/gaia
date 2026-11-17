import { FIXED_LOCALE, formatDate, formatTime } from "@shared/utils";

/**
 * Utilities for handling datetime-local format without timezone conversion issues
 *
 * The datetime-local format (YYYY-MM-DDTHH:mm) is timezone-naive.
 * These utilities ensure we work with local time consistently without unwanted UTC conversions.
 */

/**
 * Convert a Date object to datetime-local string format (YYYY-MM-DDTHH:mm)
 * Preserves the local time without timezone conversion
 *
 * @param date - Date object in local timezone
 * @returns datetime-local format string
 */
export const toDateTimeLocalString = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");

  return `${year}-${month}-${day}T${hours}:${minutes}`;
};

/**
 * Parse a datetime-local string to Date object in local timezone
 * Handles both datetime-local format and ISO strings
 *
 * @param dateTimeLocalStr - datetime-local string (YYYY-MM-DDTHH:mm) or ISO string
 * @returns Date object in local timezone
 */
export const fromDateTimeLocalString = (dateTimeLocalStr: string): Date => {
  // If it's already an ISO string with timezone info, parse it directly
  if (
    dateTimeLocalStr.includes("Z") ||
    /[+-]\d{2}:\d{2}$/.test(dateTimeLocalStr)
  ) {
    return new Date(dateTimeLocalStr);
  }

  // For datetime-local format (no timezone), create Date in local timezone
  const [datePart, timePart] = dateTimeLocalStr.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hours, minutes] = timePart ? timePart.split(":").map(Number) : [0, 0];

  return new Date(year, month - 1, day, hours, minutes);
};

/**
 * Convert ISO string to datetime-local format preserving local time
 * Useful when receiving ISO strings from API that should be displayed in local time
 *
 * @param isoString - ISO format string
 * @returns datetime-local format string
 */
export const isoToDateTimeLocal = (isoString: string): string => {
  const date = new Date(isoString);
  return toDateTimeLocalString(date);
};

/**
 * Convert datetime-local string to ISO string for API submission
 * Preserves the local time and adds timezone info
 *
 * @param dateTimeLocalStr - datetime-local format string
 * @returns ISO string with timezone
 */
export const dateTimeLocalToISO = (dateTimeLocalStr: string): string => {
  const date = fromDateTimeLocalString(dateTimeLocalStr);
  return date.toISOString();
};

/** A datetime-local value as a date and time: "November 16, 2026, 3:45 PM". */
export const formatDateTimeLocal = (dateTimeLocalStr: string): string => {
  if (!dateTimeLocalStr) return "";
  const date = fromDateTimeLocalString(dateTimeLocalStr);
  if (Number.isNaN(date.getTime())) return "";
  return `${formatDate(date, "long", { locale: FIXED_LOCALE })}, ${formatTime(date, { locale: FIXED_LOCALE })}`;
};

/** A datetime-local value's day: "November 16, 2026". */
export const formatDateLocal = (dateTimeLocalStr: string): string => {
  if (!dateTimeLocalStr) return "";
  const date = fromDateTimeLocalString(dateTimeLocalStr);
  if (Number.isNaN(date.getTime())) return "";
  return formatDate(date, "long", { locale: FIXED_LOCALE });
};

/**
 * Get start of day in datetime-local format
 *
 * @returns datetime-local string for start of day (00:00)
 */
export const getStartOfDay = (date: Date): string => {
  const startOfDay = new Date(date);
  startOfDay.setHours(0, 0, 0, 0);
  return toDateTimeLocalString(startOfDay);
};

/**
 * Get end of day in datetime-local format
 *
 * @returns datetime-local string for end of day (23:59)
 */
export const getEndOfDay = (date: Date): string => {
  const endOfDay = new Date(date);
  endOfDay.setHours(23, 59, 0, 0);
  return toDateTimeLocalString(endOfDay);
};
