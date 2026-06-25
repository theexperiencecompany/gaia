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
const getTimezoneInfo = (timezone: string): TimezoneInfo => {
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
const getPopularTimezones = (): TimezoneInfo[] => {
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
const getAllTimezones = (): TimezoneInfo[] => {
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

// IANA ids don't encode the country, so searching "india" wouldn't match
// "Asia/Kolkata". This maps the common zones to country/alias keywords so a
// country search resolves. City, region and offset are always searchable; this
// only adds the country dimension for the zones people actually search by name.
const TZ_COUNTRY_KEYWORDS: Record<string, string> = {
  "Asia/Kolkata": "india bharat",
  "Asia/Calcutta": "india bharat",
  "Asia/Karachi": "pakistan",
  "Asia/Dhaka": "bangladesh",
  "Asia/Colombo": "sri lanka",
  "Asia/Kathmandu": "nepal",
  "Asia/Tokyo": "japan",
  "Asia/Shanghai": "china",
  "Asia/Hong_Kong": "hong kong china",
  "Asia/Taipei": "taiwan",
  "Asia/Singapore": "singapore",
  "Asia/Kuala_Lumpur": "malaysia",
  "Asia/Jakarta": "indonesia",
  "Asia/Bangkok": "thailand",
  "Asia/Ho_Chi_Minh": "vietnam",
  "Asia/Manila": "philippines",
  "Asia/Seoul": "south korea korea",
  "Asia/Dubai": "uae united arab emirates",
  "Asia/Riyadh": "saudi arabia",
  "Asia/Jerusalem": "israel",
  "Asia/Tehran": "iran",
  "Asia/Istanbul": "turkey turkiye",
  "Europe/Istanbul": "turkey turkiye",
  "Europe/London": "united kingdom uk england britain gb",
  "Europe/Dublin": "ireland",
  "Europe/Paris": "france",
  "Europe/Berlin": "germany deutschland",
  "Europe/Madrid": "spain espana",
  "Europe/Rome": "italy italia",
  "Europe/Amsterdam": "netherlands holland",
  "Europe/Brussels": "belgium",
  "Europe/Zurich": "switzerland",
  "Europe/Vienna": "austria",
  "Europe/Stockholm": "sweden",
  "Europe/Oslo": "norway",
  "Europe/Copenhagen": "denmark",
  "Europe/Helsinki": "finland",
  "Europe/Warsaw": "poland",
  "Europe/Lisbon": "portugal",
  "Europe/Athens": "greece",
  "Europe/Moscow": "russia",
  "Europe/Kyiv": "ukraine",
  "Europe/Kiev": "ukraine",
  "America/New_York": "united states usa america us",
  "America/Chicago": "united states usa america us",
  "America/Denver": "united states usa america us",
  "America/Los_Angeles": "united states usa america us",
  "America/Toronto": "canada",
  "America/Vancouver": "canada",
  "America/Mexico_City": "mexico",
  "America/Sao_Paulo": "brazil brasil",
  "America/Buenos_Aires": "argentina",
  "America/Argentina/Buenos_Aires": "argentina",
  "America/Bogota": "colombia",
  "America/Lima": "peru",
  "America/Santiago": "chile",
  "Africa/Cairo": "egypt",
  "Africa/Johannesburg": "south africa",
  "Africa/Lagos": "nigeria",
  "Africa/Nairobi": "kenya",
  "Africa/Casablanca": "morocco",
  "Australia/Sydney": "australia",
  "Australia/Melbourne": "australia",
  "Australia/Perth": "australia",
  "Pacific/Auckland": "new zealand nz",
};

/**
 * A lowercase, space-joined searchable string for a timezone: its IANA path,
 * city, region/continent, country keywords, and the UTC offset in several forms
 * ("+05:30", "+5:30", "05:30", "5:30", "utc+5:30") so a `.includes(query)` match
 * works for city, country, region and offset alike.
 */
export const timezoneSearchText = (value: string, offset: string): string => {
  const parts = value.replaceAll("_", " ").split("/");
  const city = parts.at(-1) ?? value;
  const region = parts.slice(0, -1).join(" ");
  const country = TZ_COUNTRY_KEYWORDS[value] ?? "";

  let offsets = offset;
  const m = /^([+-])(\d{2}):(\d{2})$/.exec(offset);
  if (m) {
    const [, sign, hh, mm] = m;
    const h = String(Number(hh));
    offsets = [
      offset,
      `${sign}${h}:${mm}`,
      `${hh}:${mm}`,
      `${h}:${mm}`,
      `utc${sign}${h}:${mm}`,
      `gmt${sign}${h}:${mm}`,
    ].join(" ");
  }

  return `${value} ${city} ${region} ${country} ${offsets}`.toLowerCase();
};
