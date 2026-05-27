export function getUserTimezone(): string {
  if (typeof globalThis !== "undefined" && "window" in globalThis) {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch (error) {
      console.warn("Failed to detect timezone, using UTC as fallback:", error);
      return "UTC";
    }
  }
  // Default to UTC on server-side
  return "UTC";
}
