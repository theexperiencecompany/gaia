/**
 * Calendar date formatting utilities - centralized and deduplicated
 */

/**
 * Format date with relative labels (Today, Tomorrow, Yesterday)
 */
export const formatDateWithRelative = (dateString: string): string => {
  const date = new Date(dateString);
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const compareDate = new Date(date);
  compareDate.setHours(0, 0, 0, 0);

  const fullDate = date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  if (compareDate.getTime() === today.getTime()) {
    return `${fullDate} (Today)`;
  } else if (compareDate.getTime() === tomorrow.getTime()) {
    return `${fullDate} (Tomorrow)`;
  } else if (compareDate.getTime() === yesterday.getTime()) {
    return `${fullDate} (Yesterday)`;
  } else {
    return fullDate;
  }
};

/**
 * Format time range for display (e.g., "10 – 11 AM", "9 AM – 2 PM")
 */
export const formatTimeRange = (startTime: string, endTime: string): string => {
  const start = new Date(startTime);
  const end = new Date(endTime);

  const formatTimeString = (date: Date) => {
    const hours = date.getHours();
    const minutes = date.getMinutes();
    const ampm = hours >= 12 ? "PM" : "AM";
    const hour12 = hours % 12 || 12;
    const minuteStr = minutes.toString().padStart(2, "0");

    if (minutes === 0) {
      return `${hour12} ${ampm}`;
    }
    return `${hour12}:${minuteStr} ${ampm}`;
  };

  const startStr = formatTimeString(start);
  const endStr = formatTimeString(end);

  if (start.getHours() < 12 && end.getHours() >= 12) {
    return `${startStr} – ${endStr}`;
  } else if (start.getHours() >= 12 && end.getHours() >= 12) {
    return `${startStr.replace(" PM", "")} – ${endStr}`;
  } else if (start.getHours() < 12 && end.getHours() < 12) {
    return `${startStr.replace(" AM", "")} – ${endStr}`;
  }

  return `${startStr} – ${endStr}`;
};

/**
 * Format date for all-day events
 */
export const formatAllDayDate = (dateString: string): string => {
  try {
    const date = new Date(dateString);
    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(date);
  } catch (error) {
    console.error("Error formatting all-day date:", error);
    return dateString;
  }
};

/**
 * Format datetime for timed events
 */
export const formatTimedEventDate = (isoString: string): string => {
  try {
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
  } catch (error) {
    console.error("Error formatting timed event date:", error);
    return isoString;
  }
};

/**
 * Format date range for all-day events
 */
export const formatAllDayDateRange = (
  startDate: string,
  endDate: string,
): string => {
  try {
    const start = new Date(startDate);
    const end = new Date(endDate);

    if (start.toDateString() === end.toDateString()) {
      return formatAllDayDate(startDate);
    }

    const startFormatted = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
    }).format(start);

    const endFormatted = new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(end);

    return `${startFormatted} - ${endFormatted}`;
  } catch (error) {
    console.error("Error formatting date range:", error);
    return `${startDate} - ${endDate}`;
  }
};

/**
 * Check if a date string is date-only (no time)
 */
export const isDateOnly = (dateString: string): boolean => {
  return /^\d{4}-\d{2}-\d{2}$/.test(dateString);
};

/**
 * Get event duration text
 */
export const getEventDurationText = (
  startDate: string,
  endDate?: string,
): string => {
  if (!endDate) return "Single event";

  try {
    const start = new Date(startDate);
    const end = new Date(endDate);
    const diffMs = end.getTime() - start.getTime();
    const diffHours = diffMs / (1000 * 60 * 60);

    if (diffHours < 1) {
      const diffMinutes = Math.round(diffMs / (1000 * 60));
      return `${diffMinutes} minute${diffMinutes !== 1 ? "s" : ""}`;
    } else if (diffHours < 24) {
      const hours = Math.round(diffHours);
      return `${hours} hour${hours !== 1 ? "s" : ""}`;
    } else {
      const days = Math.round(diffHours / 24);
      return `${days} day${days !== 1 ? "s" : ""}`;
    }
  } catch {
    return "Duration unknown";
  }
};

