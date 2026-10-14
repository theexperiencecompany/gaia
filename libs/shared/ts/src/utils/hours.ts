/**
 * Whole-hour clock helpers. Deterministic on purpose: no locale lookups, so a
 * label renders the same on the server and the client.
 */

export type Meridiem = "AM" | "PM";

/** 0-23 to its 12-hour reading: 0 is 12 AM, 12 is 12 PM. */
export const to12Hour = (
  hour24: number,
): { hour12: number; ampm: Meridiem } => {
  if (hour24 === 0) return { hour12: 12, ampm: "AM" };
  if (hour24 === 12) return { hour12: 12, ampm: "PM" };
  if (hour24 < 12) return { hour12: hour24, ampm: "AM" };
  return { hour12: hour24 - 12, ampm: "PM" };
};

/** A 12-hour reading back to 0-23. */
export const to24Hour = (hour12: number, ampm: Meridiem): number => {
  if (ampm === "AM") return hour12 === 12 ? 0 : hour12;
  return hour12 === 12 ? 12 : hour12 + 12;
};

/** 22 -> "10 PM", 0 -> "12 AM". */
export const formatHour12 = (hour24: number): string => {
  const { hour12, ampm } = to12Hour(hour24);
  return `${hour12} ${ampm}`;
};
