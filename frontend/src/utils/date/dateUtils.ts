import { isValid, parseISO } from "date-fns";

const nth = (date: number): string => {
  if (date > 3 && date < 21) return "th";
  switch (date % 10) {
    case 1:
      return "st";
    case 2:
      return "nd";
    case 3:
      return "rd";
    default:
      return "th";
  }
};

export default function fetchDate(): string {
  return new Date().toISOString();
}

export const parsingDate = (isoString: string) => {
  const withoutTimezone = isoString.replace(/([+-]\d{2}:\d{2})$/, "");
  const date = new Date(withoutTimezone);
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    hour12: true,
  }).format(date);
};

export function parseDate(isoDateString: string): string {
  const date = new Date(isoDateString);
  const now = new Date();
  const diffInMs = now.getTime() - date.getTime();

  // Format the actual time for display in brackets
  const optionsTime: Intl.DateTimeFormatOptions = {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  };
  const formattedTime = date
    .toLocaleString(navigator.language, optionsTime)
    .toUpperCase();

  // Show exact relative time for recent dates (within 7 days)
  if (diffInMs < 7 * 24 * 60 * 60 * 1000) {
    // 7 days in milliseconds
    const seconds = Math.floor(diffInMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    let relativeTime = "";

    if (days > 0) {
      const remainingHours = hours % 24;
      relativeTime = days === 1 ? "1 day" : `${days} days`;
      if (remainingHours > 0) {
        relativeTime +=
          remainingHours === 1 ? " 1 hour" : ` ${remainingHours} hours`;
      }
    } else if (hours > 0) {
      const remainingMinutes = minutes % 60;
      relativeTime = hours === 1 ? "1 hour" : `${hours} hours`;
      if (remainingMinutes > 0) {
        relativeTime +=
          remainingMinutes === 1 ? " 1 min" : ` ${remainingMinutes} mins`;
      }
    } else if (minutes > 0) {
      relativeTime = minutes === 1 ? "1 min" : `${minutes} mins`;
    } else {
      relativeTime = "just now";
    }

    return relativeTime === "just now"
      ? `${relativeTime} (${formattedTime})`
      : `${relativeTime} ago (${formattedTime})`;
  }

  // For older dates, show the full date format
  const optionsMonth: Intl.DateTimeFormatOptions = { month: "short" };
  const optionsYear: Intl.DateTimeFormatOptions = { year: "2-digit" };

  const month = date.toLocaleString(navigator.language, optionsMonth);
  const year = date.toLocaleString(navigator.language, optionsYear);
  const day = date.getDate();

  return `${day}${nth(day)} ${month} '${year} (${formattedTime})`;
}

export function parseDate2(isoDateString: string): string {
  const date = new Date(isoDateString);
  const optionsMonth: Intl.DateTimeFormatOptions = { month: "short" };
  const month = date.toLocaleString(navigator.language, optionsMonth);
  const day = date.getDate();

  return `${day}${nth(day)} ${month}`.trim();
}

/**
 * Formats a date string into a human-readable date format
 * Examples: "June 10, 2025", "March 15, 2024", "December 1, 2023"
 *
 * @param dateString - Date string in ISO format (YYYY-MM-DD) or any valid date format
 * @returns Human-readable date string
 */
export function formatRelativeDate(dateString: string): string {
  try {
    // Try to parse the date string
    let date: Date;

    // If it's in YYYY-MM-DD format, parse it as ISO
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
      date = parseISO(dateString);
    } else {
      // Try parsing as a regular date string
      date = new Date(dateString);
    }

    // Check if the date is valid
    if (!isValid(date)) {
      console.warn(`Invalid date string: ${dateString}`);
      return dateString; // Return original string if parsing fails
    }

    // Format as readable date
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch (error) {
    console.warn(`Error formatting date: ${dateString}`, error);
    return dateString; // Return original string if error occurs
  }
}
