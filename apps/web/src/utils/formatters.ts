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
