import { useMemo } from "react";

import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

export interface EventPosition {
  event: GoogleCalendarEvent;
  top: number;
  height: number;
  left: number;
  width: number;
}

export interface CalendarEventPositions {
  allDayEvents: GoogleCalendarEvent[];
  timedEvents: EventPosition[];
}

const HOUR_HEIGHT = 64; // 64px per hour (h-16 in Tailwind)
const START_HOUR = 0; // 12AM (midnight)
const PIXELS_PER_MINUTE = HOUR_HEIGHT / 60;

const calculateEventPosition = (
  event: GoogleCalendarEvent,
): Omit<EventPosition, "left" | "width"> | null => {
  const eventStart = new Date(event.start.dateTime || event.start.date || "");
  const eventEnd = new Date(event.end.dateTime || event.end.date || "");

  // Handle timed events only (all-day events are handled separately)
  if (event.start.dateTime && event.end.dateTime) {
    const startHour = eventStart.getHours();
    const startMinute = eventStart.getMinutes();
    const endHour = eventEnd.getHours();
    const endMinute = eventEnd.getMinutes();

    if (startHour >= START_HOUR && startHour <= 23) {
      const top =
        ((startHour - START_HOUR) * 60 + startMinute) * PIXELS_PER_MINUTE;
      const height = Math.max(
        ((endHour - startHour) * 60 + (endMinute - startMinute)) *
          PIXELS_PER_MINUTE,
        50,
      );

      return {
        event,
        top,
        height,
      };
    }
  }

  return null;
};

const calculateOverlaps = (dayEvents: EventPosition[]): void => {
  if (dayEvents.length <= 1) return;

  const sortedEvents = dayEvents.sort((a, b) => a.top - b.top);
  const overlapGroups: EventPosition[][] = [];

  sortedEvents.forEach((event) => {
    const overlappingGroups = overlapGroups.filter((group) =>
      group.some(
        (existingEvent) =>
          event.top < existingEvent.top + existingEvent.height &&
          event.top + event.height > existingEvent.top,
      ),
    );

    if (overlappingGroups.length === 0) {
      overlapGroups.push([event]);
    } else if (overlappingGroups.length === 1) {
      overlappingGroups[0].push(event);
    } else {
      const mergedGroup = [event];
      overlappingGroups.forEach((group) => {
        mergedGroup.push(...group);
        const index = overlapGroups.indexOf(group);
        overlapGroups.splice(index, 1);
      });
      overlapGroups.push(mergedGroup);
    }
  });

  overlapGroups.forEach((group) => {
    const groupSize = group.length;
    const columnWidth = 100 / groupSize;

    group.forEach((event, index) => {
      event.left = index * columnWidth;
      event.width = columnWidth - 1;
    });
  });
};

export const useCalendarEventPositioning = (
  events: GoogleCalendarEvent[],
  selectedDate: Date,
): CalendarEventPositions => {
  return useMemo(() => {
    const selectedDateStr = selectedDate.toDateString();
    const allDayEvents: GoogleCalendarEvent[] = [];
    const timedEvents: EventPosition[] = [];

    events.forEach((event) => {
      const eventStart = new Date(
        event.start.dateTime || event.start.date || "",
      );

      if (eventStart.toDateString() === selectedDateStr) {
        // Check if it's an all-day event (has date but no dateTime)
        if (event.start.date && !event.start.dateTime) {
          allDayEvents.push(event);
        } else {
          // It's a timed event
          const position = calculateEventPosition(event);
          if (position) {
            timedEvents.push({
              ...position,
              left: 0,
              width: 100,
            });
          }
        }
      }
    });

    calculateOverlaps(timedEvents);

    return { allDayEvents, timedEvents };
  }, [selectedDate, events]);
};
