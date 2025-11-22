import { format, isThisYear, isToday, isYesterday } from "date-fns";

/**
 * Formats a date string for chat message date separators
 * Returns "Today", "Yesterday", or formatted date based on when the message was sent
 */
export const formatMessageDate = (dateString: string): string => {
  const date = new Date(dateString);

  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";

  // For current year, show "MMM dd" (e.g., "Jan 15")
  // For previous years, show "MMM dd, yyyy" (e.g., "Jan 15, 2023")
  return isThisYear(date)
    ? format(date, "MMM dd")
    : format(date, "MMM dd, yyyy");
};

/**
 * Checks if two dates are on different days
 * Used to determine when to show a date separator
 */
export const isDifferentDay = (date1: string, date2: string): boolean => {
  const d1 = new Date(date1);
  const d2 = new Date(date2);

  return (
    d1.getFullYear() !== d2.getFullYear() ||
    d1.getMonth() !== d2.getMonth() ||
    d1.getDate() !== d2.getDate()
  );
};
