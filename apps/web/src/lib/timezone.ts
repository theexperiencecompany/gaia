/**
 * Canonical timezone module for the web app — the single source of truth.
 *
 * Mirrors the backend `app/utils/timezone.py`. A timezone is a branded string
 * so it cannot be confused with an arbitrary `string`: mint one only via
 * `parseTimezone` / `getBrowserTimezone` / `getUserHomeTimezone`, all of which
 * validate. Two concepts, kept apart:
 *
 *  - **Home timezone** — where the user lives. `getUserHomeTimezone()`
 *    (profile, else browser). Default for new schedules, display, etc.
 *  - **Schedule timezone** — the zone one workflow/reminder fires in; stored on
 *    the task, defaulting to the home timezone.
 *
 * The browser zone is read in exactly one place — the shared `getUserTimezone`
 * (also used for the `x-timezone` header and by non-web consumers) — and this
 * module wraps it so the whole app has a single implementation.
 */

import { getUserTimezone } from "@shared/api/timezone";

import { useUserStore } from "@/stores/userStore";

export {
  getCurrentBrowserTimezone,
  getTimezoneList,
  normalizeTimezone,
  type TimezoneInfo,
} from "@/utils/timezoneUtils";

declare const timezoneBrand: unique symbol;

/** A validated IANA timezone string. Construct only via the helpers below. */
export type Timezone = string & { readonly [timezoneBrand]: true };

/** Whether `raw` is an IANA zone the runtime accepts (narrows to `Timezone`). */
export const isValidTimezone = (
  raw: string | null | undefined,
): raw is Timezone => {
  if (!raw) return false;
  try {
    // Throws RangeError for an unknown IANA zone.
    new Intl.DateTimeFormat("en-US", { timeZone: raw });
    return true;
  } catch {
    return false;
  }
};

/** Validate `raw` into a `Timezone`, falling back to UTC. */
export const parseTimezone = (raw: string | null | undefined): Timezone =>
  isValidTimezone(raw) ? raw : ("UTC" as Timezone);

/**
 * The browser's IANA timezone (e.g. "Asia/Kolkata"), via the single shared
 * reader. Falls back to UTC off the main thread / on failure.
 */
export const getBrowserTimezone = (): Timezone =>
  parseTimezone(getUserTimezone());

/**
 * The user's home timezone: their saved profile zone, falling back to the
 * browser's. A stored "UTC" is treated as low-confidence (often a junk default)
 * and yields to the live browser zone — mirrors the backend resolver's heal.
 */
export const getUserHomeTimezone = (): Timezone => {
  const profile = useUserStore.getState().timezone?.trim();
  if (profile && profile.toUpperCase() !== "UTC" && isValidTimezone(profile)) {
    return profile;
  }
  return getBrowserTimezone();
};
