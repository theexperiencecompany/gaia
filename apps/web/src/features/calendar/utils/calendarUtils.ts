import tinycolor from "tinycolor2";

import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

// Determine which color to use for the event (as a Tailwind class).
export function getEventColor(event: GoogleCalendarEvent): string {
  switch (event.eventType) {
    case "birthday":
      return "bg-pink-500 hover:bg-pink-600";
    case "outOfOffice":
      return "bg-teal-500 hover:bg-teal-600";
    default:
      if (event.transparency === "transparent")
        return "bg-purple-500 hover:bg-purple-600";
      return "bg-blue-500 hover:bg-blue-600";
  }
}

export function isTooDark(color: string, threshold: number = 0.04): boolean {
  const luminance = tinycolor(color).getLuminance();
  return luminance < threshold;
}
