/**
 * Timezone utilities for displaying timezone information with offsets.
 * Uses the native Intl API — zero bundle cost, no external dependencies.
 */

export interface TimezoneInfo {
  value: string;
  label: string;
  offset: string;
  abbreviation: string;
  formattedLabel: string;
  currentTime: string;
}

/**
 * Returns a UTC offset string like "+05:30" or "-05:00" for the given IANA
 * timezone, derived from Intl.DateTimeFormat's "shortOffset" timeZoneName.
 */
const getOffsetString = (timezone: string): string => {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: timezone,
    timeZoneName: "shortOffset",
  }).formatToParts(new Date());

  const tzPart = parts.find((p) => p.type === "timeZoneName")?.value ?? "GMT";

  // shortOffset produces values like "GMT+5:30", "GMT-5", "GMT"
  const match = tzPart.match(/GMT([+-]\d+(?::\d+)?)?/);
  if (!match || !match[1]) return "+00:00";

  const [hours, mins = "00"] = match[1].split(":");
  const sign = hours.startsWith("-") ? "-" : "+";
  const paddedHours = String(Math.abs(Number(hours))).padStart(2, "0");
  const paddedMins = mins.padStart(2, "0");
  return `${sign}${paddedHours}:${paddedMins}`;
};

/**
 * Returns the short timezone abbreviation like "IST", "PST", "CET" for the
 * given IANA timezone.
 */
const getAbbreviation = (timezone: string): string => {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: timezone,
    timeZoneName: "short",
  }).formatToParts(new Date());

  return parts.find((p) => p.type === "timeZoneName")?.value ?? "";
};

/**
 * Returns the current local time in HH:mm format for the given IANA timezone.
 */
const getCurrentTime = (timezone: string): string => {
  return new Intl.DateTimeFormat("en", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());
};

/**
 * Extracts a human-readable city/region label from an IANA timezone identifier,
 * e.g. "Asia/Kolkata" -> "Kolkata".
 */
const getTimezoneDisplayName = (timezone: string): string => {
  const parts = timezone.split("/");
  if (parts.length >= 2) {
    return parts[parts.length - 1].replace(/_/g, " ");
  }
  return timezone;
};

/**
 * Normalise a timezone string to a valid IANA identifier.
 * Handles legacy aliases (e.g. "Asia/Calcutta" -> "Asia/Kolkata") and
 * validates the result against Intl. Falls back to the original string when
 * validation is not possible.
 */
export const normalizeTimezone = (timezone: string): string => {
  if (!timezone) return "UTC";

  const legacyMap: Record<string, string> = {
    "Asia/Calcutta": "Asia/Kolkata",
  };

  if (legacyMap[timezone]) {
    return legacyMap[timezone];
  }

  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone });
    return timezone;
  } catch {
    return timezone;
  }
};

/**
 * Builds a TimezoneInfo object for the given IANA timezone identifier using
 * only the native Intl API.
 */
export const getTimezoneInfo = (timezone: string): TimezoneInfo => {
  try {
    const offset = getOffsetString(timezone);
    const abbreviation = getAbbreviation(timezone);
    const currentTime = getCurrentTime(timezone);
    const cityName = getTimezoneDisplayName(timezone);

    return {
      value: timezone,
      label: cityName,
      offset,
      abbreviation,
      currentTime,
      formattedLabel: `${cityName} (UTC${offset}) - ${currentTime}`,
    };
  } catch (error) {
    console.warn(`Error getting timezone info for ${timezone}:`, error);
    return {
      value: timezone,
      label: timezone,
      offset: "+00:00",
      abbreviation: "",
      currentTime: "--:--",
      formattedLabel: timezone,
    };
  }
};

/**
 * Returns a TimezoneInfo for the timezone currently reported by the browser /
 * Node.js runtime.
 */
export const getCurrentBrowserTimezone = (): TimezoneInfo => {
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const normalizedTimezone = normalizeTimezone(browserTimezone);
  return getTimezoneInfo(normalizedTimezone);
};

/**
 * Returns a sorted list of commonly-used timezone entries.
 */
export const getPopularTimezones = (): TimezoneInfo[] => {
  const popularTimezones = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Toronto",
    "America/Sao_Paulo",
    "America/Mexico_City",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Rome",
    "Europe/Madrid",
    "Europe/Amsterdam",
    "Europe/Zurich",
    "Europe/Stockholm",
    "Europe/Moscow",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Singapore",
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Seoul",
    "Asia/Bangkok",
    "Australia/Sydney",
    "Australia/Melbourne",
    "Pacific/Auckland",
  ];

  return popularTimezones.map(getTimezoneInfo).sort((a, b) => {
    const offsetA = parseFloat(a.offset.replace(":", "."));
    const offsetB = parseFloat(b.offset.replace(":", "."));
    if (offsetA !== offsetB) {
      return offsetA - offsetB;
    }
    return a.label.localeCompare(b.label);
  });
};

/**
 * Returns a sorted list of every IANA timezone supported by the runtime,
 * obtained via Intl.supportedValuesOf("timeZone") (Node 18+ / modern browsers).
 * No timezone data bundle is needed.
 */
export const getAllTimezones = (): TimezoneInfo[] => {
  return Intl.supportedValuesOf("timeZone")
    .map(getTimezoneInfo)
    .sort((a, b) => {
      const offsetA = parseFloat(a.offset.replace(":", "."));
      const offsetB = parseFloat(b.offset.replace(":", "."));
      if (offsetA !== offsetB) {
        return offsetA - offsetB;
      }
      return a.label.localeCompare(b.label);
    });
};

/**
 * Returns either the popular or the full timezone list.
 */
export const getTimezoneList = (includeAll = false): TimezoneInfo[] => {
  return includeAll ? getAllTimezones() : getPopularTimezones();
};

/**
 * Formats a timezone for display in settings UI, e.g. "Kolkata (UTC+05:30)".
 * Falls back to the browser timezone when the argument is null or undefined.
 */
export const formatTimezoneDisplay = (
  timezone: string | null | undefined,
): string => {
  if (!timezone) {
    const browserTz = getCurrentBrowserTimezone();
    return `${browserTz.label} (UTC${browserTz.offset})`;
  }

  const tzInfo = getTimezoneInfo(timezone);
  return `${tzInfo.label} (UTC${tzInfo.offset})`;
};

/**
 * Returns simple current-time information for the browser's local timezone.
 */
export const getCurrentTimezoneInfo = (): {
  timezone: string;
  timeString: string;
  offset: string;
} => {
  const browserTz = getCurrentBrowserTimezone();
  return {
    timezone: browserTz.label,
    timeString: browserTz.currentTime,
    offset: browserTz.offset,
  };
};
