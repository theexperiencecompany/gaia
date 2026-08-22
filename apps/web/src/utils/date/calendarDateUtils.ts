/**
 * Calendar date formatting utilities - centralized and deduplicated
 */

/**
 * Format date with relative labels (Today, Tomorrow, Yesterday)
 */
export const formatDateWithRelative = (dateString: string): string => {
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
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

  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "";
  }

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
 * Check if a date string is date-only (no time)
 */
export const isDateOnly = (dateString: string): boolean => {
  return /^\d{4}-\d{2}-\d{2}$/.test(dateString);
};
