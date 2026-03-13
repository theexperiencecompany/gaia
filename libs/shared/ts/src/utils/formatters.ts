/**
 * Format a number into a compact human-readable string with suffixes.
 * Examples: 1000 -> "1k", 2600 -> "2.6k", 1200000 -> "1.2M"
 *
 * @param num - The number to format
 * @returns Formatted string with suffix
 */
export function formatCompactNumber(num: number): string {
  if (num === 0) return "0";

  const absNum = Math.abs(num);
  const sign = num < 0 ? "-" : "";

  if (absNum < 1000) {
    return sign + absNum.toString();
  }

  if (absNum < 1000000) {
    const thousands = absNum / 1000;
    return (
      sign +
      (thousands % 1 === 0 ? thousands.toFixed(0) : thousands.toFixed(1)) +
      "k"
    );
  }

  if (absNum < 1000000000) {
    const millions = absNum / 1000000;
    return (
      sign +
      (millions % 1 === 0 ? millions.toFixed(0) : millions.toFixed(1)) +
      "M"
    );
  }

  const billions = absNum / 1000000000;
  return (
    sign +
    (billions % 1 === 0 ? billions.toFixed(0) : billions.toFixed(1)) +
    "B"
  );
}

export function formatRunCount(count: number): string {
  if (count === 0) {
    return "Never run";
  }

  if (count === 1) {
    return "Ran once";
  }

  return `${formatCompactNumber(count)} runs`;
}

/**
 * Format execution duration.
 */
export function formatDuration(seconds: number | undefined): string {
  if (!seconds) return "";
  if (seconds < 60) return `Ran for ${Math.round(seconds)}s`;
  if (seconds < 3600) return `Ran for ${Math.round(seconds / 60)}m`;
  return `Ran for ${Math.round(seconds / 3600)}h`;
}

/**
 * Format a date into a relative string.
 */
export function formatRelativeDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/**
 * Get a display label for a trigger type.
 */
export function getTriggerLabel(triggerType: string): string {
  switch (triggerType) {
    case "schedule":
      return "Scheduled";
    case "manual":
      return "Manual";
    default:
      return triggerType
        .split("_")
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
  }
}

/**
 * Format a file size in bytes to a human-readable string.
 * Examples: 1024 -> "1 KB", 1048576 -> "1 MB"
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  const value = bytes / 1024 ** index;
  const formatted =
    value % 1 === 0 ? value.toFixed(0) : value.toFixed(1);
  return `${formatted} ${units[index]}`;
}

/**
 * Truncate text to a maximum length, appending an ellipsis if truncated.
 */
export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}

/**
 * Format a number with K/M/B suffixes for compact display.
 * Alias for formatCompactNumber with a name matching the task spec.
 */
export function formatNumber(num: number): string {
  return formatCompactNumber(num);
}

const URL_REGEX =
  /https?:\/\/(?:[-\w]+\.)+[a-z]{2,}(?:\/[-\w%_.~+]*)*(?:\?[-\w%_.~+=&]*)?(?:#[-\w]*)?/gi;

/**
 * Extract all HTTP/HTTPS URLs found in the given text.
 */
export function extractUrls(text: string): string[] {
  return text.match(URL_REGEX) ?? [];
}

/**
 * Format a monetary amount as a locale currency string.
 * Defaults to USD.
 */
export function formatCurrency(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}
