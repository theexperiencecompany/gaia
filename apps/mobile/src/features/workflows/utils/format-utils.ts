/**
 * Format a number into a compact human-readable string with suffixes.
 * Matches web's formatCompactNumber.
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

/**
 * Format run count for display. Matches web's formatRunCount.
 */
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
 * Format execution duration. Matches web's formatDuration.
 */
export function formatDuration(seconds: number | undefined): string {
  if (!seconds) return "";
  if (seconds < 60) return `Ran for ${Math.round(seconds)}s`;
  if (seconds < 3600) return `Ran for ${Math.round(seconds / 60)}m`;
  return `Ran for ${Math.round(seconds / 3600)}h`;
}

/**
 * Format a date into a relative string. Matches web's formatRelativeDate.
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
 * Get a display label for a trigger type. Matches web's trigger display.
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
