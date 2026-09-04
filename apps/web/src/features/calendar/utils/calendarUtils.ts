import tinycolor from "tinycolor2";

import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

// Module-scope Intl formatters — constructing them is slow, so build each
// configuration once instead of on every call.
const WEEKDAY_FORMATTER = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
});
const TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

// Group events by a date string like "day dayOfWeek"
export function groupEventsByDate(
  events: GoogleCalendarEvent[],
): Record<string, GoogleCalendarEvent[]> {
  const grouped: Record<string, GoogleCalendarEvent[]> = {};

  events.forEach((event) => {
    const [day, dayOfWeek] = formatDateDay(event);
    const eventDate = `${day} ${dayOfWeek}`;

    if (!grouped[eventDate]) {
      grouped[eventDate] = [];
    }
    grouped[eventDate].push(event);
  });

  return grouped;
}

// Format a date as an abbreviated weekday (e.g. "Mon").
export function formatWeekdayShort(date: Date): string {
  return WEEKDAY_FORMATTER.format(date);
}

// Format a single date-time as a locale time string (e.g. "5:30 PM").
export function formatEventTime(date: Date): string {
  return TIME_FORMATTER.format(date);
}

// Format the day and day of week from an event's start date.
export function formatDateDay(event: GoogleCalendarEvent): [string, string] {
  const startDate = new Date(event.start.date || event.start.dateTime || "");
  const day = startDate.getDate().toString();
  const dayOfWeek = formatWeekdayShort(startDate);

  return [day, dayOfWeek];
}

// Format event time range if dateTime is available.
export function formatEventDate(event: GoogleCalendarEvent): string | null {
  if (event?.start?.dateTime && event?.end?.dateTime) {
    const startDateTime = new Date(event.start.dateTime);
    const endDateTime = new Date(event.end.dateTime);

    return `${formatEventTime(startDateTime)} - ${formatEventTime(endDateTime)}`;
  }

  return null;
}

export function getEventIcon(event: GoogleCalendarEvent): string {
  switch (event.eventType) {
    case "birthday":
      return "🎂"; // Birthday
    case "outOfOffice":
      return "🏖️"; // Out of Office
    case "reminder":
      return "⏰"; // Reminder
    case "appointment":
      return "📅"; // Appointment
    case "meeting":
      return "💼"; // Business Meeting
    case "task":
      return "📝"; // Task or To-Do
    case "holiday":
      return "🎉"; // Public or Personal Holiday
    case "work":
      return "🏢"; // Work-Related Event
    case "travel":
      return "✈️"; // Travel Event
    case "sports":
      return "⚽"; // Sports Event
    case "concert":
      return "🎵"; // Concert or Music Event
    case "party":
      return "🍾"; // Party or Celebration
    case "health":
      return "🏥"; // Medical or Health-related Event
    case "study":
      return "📖"; // Study Session or Exam
    case "wedding":
      return "💍"; // Wedding or Anniversary
    default:
      if (event.transparency === "transparent") {
        return "🔔"; // Notification for Tentative Events
      }
      return "📅"; // Default calendar Event
  }
}

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
