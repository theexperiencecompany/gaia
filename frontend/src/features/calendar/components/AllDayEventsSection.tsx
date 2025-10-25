"use client";

import { useMemo, useState } from "react";
import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";

import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface AllDayEventsSectionProps {
  events: GoogleCalendarEvent[];
  dates: Date[];
  onEventClick?: (event: GoogleCalendarEvent) => void;
  getEventColor: (event: GoogleCalendarEvent) => string;
}

interface MultiDayEventPosition {
  event: GoogleCalendarEvent;
  startDayIndex: number;
  span: number;
  row: number;
}

const getMultiDayEventPositions = (
  events: GoogleCalendarEvent[],
  dates: Date[],
): MultiDayEventPosition[] => {
  const multiDayEvents: MultiDayEventPosition[] = [];
  const processedEventIds = new Set<string>();

  // Create a map of date strings for O(1) lookup
  const dateMap = new Map<string, number>();
  dates.forEach((date, index) => {
    dateMap.set(date.toDateString(), index);
  });

  events.forEach((event) => {
    // Only process all-day events
    if (!event.start.date || !event.end.date || processedEventIds.has(event.id))
      return;

    const eventStart = new Date(event.start.date);
    const eventEnd = new Date(event.end.date);

    // Google Calendar's end date for all-day events is exclusive (next day)
    // So we subtract 1 day to get the actual last day of the event
    eventEnd.setDate(eventEnd.getDate() - 1);

    const eventStartStr = eventStart.toDateString();

    // Find the start index in our visible dates
    const startDayIndex = dateMap.get(eventStartStr);

    // Skip events that don't start in our visible date range
    if (startDayIndex === undefined) return;

    // Calculate span by checking each subsequent visible date
    let span = 1; // The start day itself
    const eventEndTime = eventEnd.getTime();

    for (let i = startDayIndex + 1; i < dates.length; i++) {
      const visibleDate = dates[i];

      // Compare timestamps instead of strings to avoid alphabetical comparison issues
      if (visibleDate.getTime() <= eventEndTime) {
        span++;
      } else {
        break;
      }
    }

    multiDayEvents.push({
      event,
      startDayIndex,
      span,
      row: 0,
    });

    processedEventIds.add(event.id);
  }); // Assign rows to avoid overlaps using interval scheduling algorithm
  multiDayEvents.sort((a, b) => {
    if (a.startDayIndex !== b.startDayIndex) {
      return a.startDayIndex - b.startDayIndex;
    }
    return b.span - a.span; // Longer events first
  });

  const rows: Array<Array<{ start: number; end: number }>> = [];

  multiDayEvents.forEach((eventPos) => {
    const eventEnd = eventPos.startDayIndex + eventPos.span - 1;

    // Find the first row where this event fits
    let assignedRow = -1;
    for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
      const row = rows[rowIndex];
      const hasConflict = row.some(
        (occupied) =>
          !(eventEnd < occupied.start || eventPos.startDayIndex > occupied.end),
      );

      if (!hasConflict) {
        assignedRow = rowIndex;
        break;
      }
    }

    // If no row found, create a new one
    if (assignedRow === -1) {
      assignedRow = rows.length;
      rows.push([]);
    }

    // Mark this position as occupied in the row
    rows[assignedRow].push({
      start: eventPos.startDayIndex,
      end: eventEnd,
    });

    eventPos.row = assignedRow;
  });

  return multiDayEvents;
};

export const AllDayEventsSection: React.FC<AllDayEventsSectionProps> = ({
  events,
  dates,
  onEventClick,
  getEventColor,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  const multiDayEvents = useMemo(
    () => getMultiDayEventPositions(events, dates),
    [events, dates],
  );

  const hasAnyAllDayEvents = multiDayEvents.length > 0;

  return (
    <div className="sticky top-0 z-[1] border-b border-zinc-800 bg-[#1a1a1a]">
      <div className="flex">
        {/* Time Label Column */}
        <div
          className="w-20 flex-shrink-0 cursor-pointer border-r border-zinc-800 transition-colors hover:bg-zinc-800/50"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          <div className="flex h-full items-center justify-end gap-1 py-3 pr-3">
            <span className="text-xs font-medium text-zinc-400">All-day</span>
            {hasAnyAllDayEvents && (
              <span>
                {isExpanded ? (
                  <ChevronsDownUp className="h-3 w-3 text-zinc-400" />
                ) : (
                  <ChevronsUpDown className="h-3 w-3 text-zinc-400" />
                )}
              </span>
            )}
          </div>
        </div>

        {/* All-day events container */}
        <div className="flex-1">
          {isExpanded ? (
            multiDayEvents.length > 0 ? (
              <div className="px-0.5 py-2">
                {Array.from(
                  { length: Math.max(...multiDayEvents.map((e) => e.row)) + 1 },
                  (_, rowIndex) => (
                    <div
                      key={`row-${rowIndex}`}
                      className="mb-1 grid last:mb-0"
                      style={{
                        gridTemplateColumns: `repeat(${dates.length}, minmax(0, 1fr))`,
                        gap: "2px",
                      }}
                    >
                      {multiDayEvents
                        .filter((eventPos) => eventPos.row === rowIndex)
                        .map((eventPos) => {
                          const eventColor = getEventColor(eventPos.event);
                          return (
                            <div
                              key={eventPos.event.id}
                              style={{
                                gridColumnStart: eventPos.startDayIndex + 1,
                                gridColumnEnd: `span ${eventPos.span}`,
                              }}
                            >
                              <div
                                className="flex h-7 cursor-pointer items-center overflow-hidden rounded-md text-white transition-opacity hover:opacity-80"
                                style={{
                                  backgroundColor: `${eventColor}40`,
                                }}
                                onClick={() => onEventClick?.(eventPos.event)}
                              >
                                <div
                                  className="h-full w-1 flex-shrink-0 rounded-l-md"
                                  style={{
                                    backgroundColor: eventColor,
                                  }}
                                />
                                <div className="flex-1 overflow-hidden px-2">
                                  <div className="truncate text-xs font-medium">
                                    {eventPos.event.summary}
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  ),
                )}
              </div>
            ) : (
              <div className="py-2" />
            )
          ) : multiDayEvents.length > 0 ? (
            <div className="flex items-center px-2 py-2 text-xs text-zinc-400">
              {multiDayEvents.length} event
              {multiDayEvents.length !== 1 ? "s" : ""}
            </div>
          ) : (
            <div className="py-2" />
          )}
        </div>
      </div>
    </div>
  );
};
