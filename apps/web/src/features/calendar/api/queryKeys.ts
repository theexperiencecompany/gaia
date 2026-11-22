/** Every calendar query key; a server calendar push invalidates the event keys. */
export const calendarKeys = {
  calendars: ["calendars"] as const,
  preferences: ["calendarPreferences"] as const,
  events: ["calendar-events"] as const,
  monthEvents: (calendarIds: readonly string[], month: string) =>
    [...calendarKeys.events, [...calendarIds].sort(), month] as const,
  upcoming: ["upcoming-events"] as const,
};
