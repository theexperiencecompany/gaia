export function getUserTimezone(): string {
  // `window` only exists in the browser. Reference it through globalThis so
  // this isomorphic util type-checks against the ES2022 lib without pulling
  // the DOM lib into the shared package, which is also consumed by Node code.
  const inBrowser = typeof globalThis !== "undefined" && "window" in globalThis;
  if (inBrowser) {
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
