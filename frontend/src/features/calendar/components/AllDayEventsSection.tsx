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

  events.forEach((event) => {
    // Only process all-day events
    if (!event.start.date || !event.end.date || processedEventIds.has(event.id))
      return;

    const eventStart = new Date(event.start.date);
    const eventEnd = new Date(event.end.date);

    // Google Calendar's end date for all-day events is exclusive (next day)
    // So we subtract 1 day to get the actual last day of the event
    eventEnd.setDate(eventEnd.getDate() - 1);

    // Find which days this event spans in our visible dates
    const startDayIndex = dates.findIndex(
      (date) => date.toDateString() === eventStart.toDateString(),
    );

    if (startDayIndex !== -1) {
      // Calculate how many days this event spans in the visible range
      let span = 1;
      const eventEndStr = eventEnd.toDateString();

      for (let i = startDayIndex + 1; i < dates.length; i++) {
        const currentDateStr = dates[i].toDateString();

        // Compare using date strings to avoid time component issues
        if (currentDateStr <= eventEndStr) {
          span++;
        } else {
          break;
        }
      }

      multiDayEvents.push({
        event,
        startDayIndex,
        span,
        row: 0, // Will be calculated later
      });

      processedEventIds.add(event.id);
    }
  });

  // Assign rows to avoid overlaps
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
    <div className="border-b border-zinc-800">
      <div className="flex">
        {/* Time Label Column - matches the time labels */}
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

        {/* All-day events grid */}
        <div className="relative flex-1">
          {isExpanded ? (
            multiDayEvents.length > 0 ? (
              <div>
                {/* Calculate the number of rows needed */}
                {Array.from(
                  {
                    length: Math.max(...multiDayEvents.map((e) => e.row)) + 1,
                  },
                  (_, rowIndex) => (
                    <div
                      key={`row-${rowIndex}`}
                      className="relative grid"
                      style={{
                        gridTemplateColumns: `repeat(${dates.length}, 1fr)`,
                        gap: "0.125rem",
                        minHeight: "36px",
                      }}
                    >
                      {/* Render events in this row */}
                      {multiDayEvents
                        .filter((eventPos) => eventPos.row === rowIndex)
                        .map((eventPos, index) => {
                          const eventColor = getEventColor(eventPos.event);
                          return (
                            <div
                              key={`multiday-${eventPos.event.id}-${index}`}
                              className="px-1"
                              style={{
                                gridColumn: `${eventPos.startDayIndex + 1} / span ${eventPos.span}`,
                              }}
                            >
                              <div
                                className="flex h-8 cursor-pointer overflow-hidden rounded-lg text-white transition-all duration-200 hover:opacity-80"
                                style={{
                                  backgroundColor: `${eventColor}40`,
                                }}
                                onClick={() => onEventClick?.(eventPos.event)}
                              >
                                <div
                                  className="w-1 flex-shrink-0 rounded-l-lg"
                                  style={{
                                    backgroundColor: eventColor,
                                  }}
                                />
                                <div className="flex flex-1 items-center overflow-hidden px-2 py-1">
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
              <div className="min-h-[32px]" />
            )
          ) : multiDayEvents.length > 0 ? (
            <div className="flex min-h-[32px] items-center px-2 text-xs text-zinc-400">
              {multiDayEvents.length} event
              {multiDayEvents.length !== 1 ? "s" : ""}
            </div>
          ) : (
            <div className="min-h-[32px]" />
          )}
        </div>
      </div>
    </div>
  );
};
