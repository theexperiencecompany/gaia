"use client";

import type { Virtualizer } from "@tanstack/react-virtual";
import { useMemo, useState } from "react";

import { UnfoldLessIcon, UnfoldMoreIcon } from "@/icons";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface AllDayEventsSectionProps {
  events: GoogleCalendarEvent[];
  dates: Date[];
  onEventClick?: (event: GoogleCalendarEvent) => void;
  getEventColor: (event: GoogleCalendarEvent) => string;
  columnVirtualizer: Virtualizer<HTMLDivElement, Element>;
  totalWidth?: number;
}

interface MultiDayEventPosition {
  event: GoogleCalendarEvent;
  startDayIndex: number;
  span: number;
  row: number;
  continuesLeft: boolean;
  continuesRight: boolean;
}

const getMultiDayEventPositions = (
  events: GoogleCalendarEvent[],
  dates: Date[],
): MultiDayEventPosition[] => {
  const multiDayEvents: MultiDayEventPosition[] = [];
  const processedEventIds = new Set<string>();

  if (dates.length === 0) return multiDayEvents;

  // Create a map of date strings for O(1) lookup
  const dateMap = new Map<string, number>();
  dates.forEach((date, index) => {
    dateMap.set(date.toDateString(), index);
  });

  const firstVisibleDate = dates[0];
  const lastVisibleDate = dates[dates.length - 1];

  events.forEach((event) => {
    // Only process all-day events
    if (!event.start.date || !event.end.date || processedEventIds.has(event.id))
      return;

    const eventStart = new Date(event.start.date);
    const eventEnd = new Date(event.end.date);

    // Google Calendar's end date for all-day events is exclusive (next day)
    // So we subtract 1 day to get the actual last day of the event
    eventEnd.setDate(eventEnd.getDate() - 1);

    // Check if event overlaps with visible date range
    if (eventEnd < firstVisibleDate || eventStart > lastVisibleDate) {
      return; // Event doesn't overlap with visible range
    }

    // Determine if event continues beyond visible range
    const continuesLeft = eventStart < firstVisibleDate;
    const continuesRight = eventEnd > lastVisibleDate;

    // Calculate the visible start of the event
    const visibleStartDate = continuesLeft ? firstVisibleDate : eventStart;
    const visibleEndDate = continuesRight ? lastVisibleDate : eventEnd;

    const startDayIndex = dateMap.get(visibleStartDate.toDateString());

    // This should always be defined now, but check for safety
    if (startDayIndex === undefined) return;

    // Calculate span within visible dates
    let span = 1;
    const visibleEndTime = visibleEndDate.getTime();

    for (let i = startDayIndex + 1; i < dates.length; i++) {
      const visibleDate = dates[i];

      if (visibleDate.getTime() <= visibleEndTime) {
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
      continuesLeft,
      continuesRight,
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
  columnVirtualizer,
  totalWidth,
}) => {
  const calculatedWidth = totalWidth || columnVirtualizer.getTotalSize();
  const [isExpanded, setIsExpanded] = useState(true);

  // Get column width from virtualizer (all columns should have same size)
  const columnWidth = columnVirtualizer.getVirtualItems()[0]?.size || 0;

  const multiDayEvents = useMemo(
    () => getMultiDayEventPositions(events, dates),
    [events, dates],
  );

  // Count events per day for collapsed view
  const eventCountsByDay = useMemo(() => {
    const counts = new Array(dates.length).fill(0);

    multiDayEvents.forEach((eventPos) => {
      // Count this event for each day it spans
      for (let i = 0; i < eventPos.span; i++) {
        const dayIndex = eventPos.startDayIndex + i;
        if (dayIndex < dates.length) {
          counts[dayIndex]++;
        }
      }
    });

    return counts;
  }, [multiDayEvents, dates.length]);

  const hasAnyAllDayEvents = multiDayEvents.length > 0;
  const maxRow =
    multiDayEvents.length > 0
      ? Math.max(...multiDayEvents.map((e) => e.row)) + 1
      : 0;
  const containerHeight = maxRow * 29;

  return (
    <div className="sticky top-[37px] z-[12] flex min-w-fit flex-shrink-0 border-b border-zinc-800 bg-primary-bg">
      {/* Time Label Column */}
      <div
        className="sticky left-0 z-[11] w-20 flex-shrink-0 cursor-pointer border-r border-zinc-800 bg-primary-bg transition-colors hover:bg-zinc-800/50"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex h-full items-center justify-end gap-1 py-3 pr-3">
          <span className="text-xs font-medium text-zinc-400 select-none">
            All-day
          </span>
          {hasAnyAllDayEvents && (
            <span>
              {isExpanded ? (
                <UnfoldLessIcon className="h-3 w-3 text-zinc-400" />
              ) : (
                <UnfoldMoreIcon className="h-3 w-3 text-zinc-400" />
              )}
            </span>
          )}
        </div>
      </div>

      {/* All-day events container */}
      {isExpanded ? (
        multiDayEvents.length > 0 ? (
          <div
            className="relative max-h-28 overflow-x-hidden overflow-y-auto"
            style={{
              width: `${calculatedWidth}px`,
            }}
          >
            {/* Inner content container with proper height */}
            <div
              className="relative py-2"
              style={{
                height: `${containerHeight + 16}px`,
              }}
            >
              {/* Column borders - full height to match scrollable content */}
              <div className="pointer-events-none absolute inset-0 flex">
                {columnVirtualizer.getVirtualItems().map((virtualColumn) => (
                  <div
                    key={`border-${virtualColumn.index}`}
                    className="absolute top-0 h-full flex-shrink-0 border-r border-zinc-800"
                    style={{
                      width: `${virtualColumn.size}px`,
                      transform: `translateX(${virtualColumn.start}px)`,
                      scrollSnapAlign: "start",
                    }}
                  />
                ))}
              </div>

              {multiDayEvents.map((eventPos) => {
                const eventColor = getEventColor(eventPos.event);
                const leftOffset = eventPos.startDayIndex * columnWidth;
                const width = eventPos.span * columnWidth - 4;

                return (
                  <div
                    key={eventPos.event.id}
                    className="absolute"
                    style={{
                      top: `${eventPos.row * 29 + 8}px`,
                      left: `${leftOffset}px`,
                      width: `${width}px`,
                      height: "28px",
                    }}
                  >
                    <div
                      className="sti flex h-7 cursor-pointer items-center overflow-hidden text-white transition-opacity hover:opacity-80"
                      style={{
                        backgroundColor: `${eventColor}40`,
                        borderTopLeftRadius: eventPos.continuesLeft
                          ? "0px"
                          : "6px",
                        borderBottomLeftRadius: eventPos.continuesLeft
                          ? "0px"
                          : "6px",
                        borderTopRightRadius: eventPos.continuesRight
                          ? "0px"
                          : "6px",
                        borderBottomRightRadius: eventPos.continuesRight
                          ? "0px"
                          : "6px",
                      }}
                      onClick={() => onEventClick?.(eventPos.event)}
                    >
                      <div
                        className="h-full flex-shrink-0"
                        style={{
                          backgroundColor: eventColor,
                          width: "4px",
                          borderTopLeftRadius: eventPos.continuesLeft
                            ? "0px"
                            : "6px",
                          borderBottomLeftRadius: eventPos.continuesLeft
                            ? "0px"
                            : "6px",
                        }}
                      />
                      <div className="flex flex-1 items-center overflow-hidden px-2">
                        {eventPos.continuesLeft && (
                          <span className="mr-1 text-xs opacity-70">←</span>
                        )}
                        <div className="flex-1 truncate text-xs font-medium">
                          {eventPos.event.summary}
                        </div>
                        {eventPos.continuesRight && (
                          <span className="ml-1 text-xs opacity-70">→</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div
            className="relative py-2"
            style={{ width: `${calculatedWidth}px` }}
          >
            {/* Column borders */}
            <div className="pointer-events-none absolute inset-0 flex">
              {columnVirtualizer.getVirtualItems().map((virtualColumn) => (
                <div
                  key={`border-${virtualColumn.index}`}
                  className="absolute top-0 h-full flex-shrink-0 border-r border-zinc-800"
                  style={{
                    width: `${virtualColumn.size}px`,
                    transform: `translateX(${virtualColumn.start}px)`,
                    scrollSnapAlign: "start",
                  }}
                />
              ))}
            </div>
          </div>
        )
      ) : multiDayEvents.length > 0 ? (
        <div
          className="relative flex"
          style={{ width: `${calculatedWidth}px`, height: "40px" }}
        >
          {columnVirtualizer.getVirtualItems().map((virtualColumn) => {
            const index = virtualColumn.index;
            const count = eventCountsByDay[index];
            return (
              <div
                key={virtualColumn.key}
                className="absolute top-0 left-0 flex flex-shrink-0 items-center justify-center border-r border-zinc-800 px-2 py-2 text-xs text-zinc-400"
                style={{
                  width: `${virtualColumn.size}px`,
                  transform: `translateX(${virtualColumn.start}px)`,
                  scrollSnapAlign: "start",
                }}
              >
                {count > 0 ? `${count} event${count !== 1 ? "s" : ""}` : ""}
              </div>
            );
          })}
        </div>
      ) : (
        <div
          className="relative py-2"
          style={{ width: `${calculatedWidth}px` }}
        >
          {/* Column borders */}
          <div className="pointer-events-none absolute inset-0 flex">
            {columnVirtualizer.getVirtualItems().map((virtualColumn) => (
              <div
                key={`border-${virtualColumn.index}`}
                className="absolute top-0 h-full flex-shrink-0 border-r border-zinc-800"
                style={{
                  width: `${virtualColumn.size}px`,
                  transform: `translateX(${virtualColumn.start}px)`,
                  scrollSnapAlign: "start",
                }}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
