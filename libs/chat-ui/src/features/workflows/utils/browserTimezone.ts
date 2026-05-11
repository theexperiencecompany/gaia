/**
 * Get the browser's IANA timezone (e.g., "America/New_York", "Asia/Kolkata").
 * Falls back to "UTC" in non-browser environments.
 */
export const getBrowserTimezone = (): string => {
  if (typeof window !== "undefined" && typeof Intl !== "undefined") {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch {
      return "UTC";
    }
  }
  return "UTC";
};
