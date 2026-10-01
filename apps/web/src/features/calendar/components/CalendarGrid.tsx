"use client";

import { Spinner } from "@heroui/react";
import type { Virtualizer } from "@tanstack/react-virtual";
import type React from "react";
import { useMemo } from "react";

import { AllDayEventsSection } from "@/features/calendar/components/AllDayEventsSection";
import {
  CurrentTimeLabel,
  CurrentTimeLine,
} from "@/features/calendar/components/CurrentTimeIndicator";
import { formatEventTime } from "@/features/calendar/utils/calendarUtils";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface MultiDayCalendarGridProps {
  hours: number[];
  dates: Date[];
  events: GoogleCalendarEvent[];
  loading: {
    calendars: boolean;
    events: boolean;
  };
  error: {
    calendars: string | null;
    events: string | null;
  };
  selectedCalendars: string[];
  onEventClick?: (event: GoogleCalendarEvent) => void;
  getEventColor: (event: GoogleCalendarEvent) => string;
  columnVirtualizer: Virtualizer<HTMLDivElement, Element>;
  isLoadingPast?: boolean;
  isLoadingFuture?: boolean;
  scrollElementRef?: React.RefObject<HTMLDivElement | null>;
}

const PX_PER_MINUTE = 64 / 60;
const DAY_START_HOUR = 0;

interface EventPosition {
  event: GoogleCalendarEvent;
  top: number;
  height: number;
  left: number;
  width: number;
}

const getEventPositions = (
  events: GoogleCalendarEvent[],
  targetDate: Date,
): { timedEvents: EventPosition[] } => {
  const targetDateStr = targetDate.toDateString();
  const timedEvents: EventPosition[] = [];

  for (const event of events) {
    const startDateTime = event.start.dateTime;
    const endDateTime = event.end.dateTime;
    if (!startDateTime || !endDateTime) continue;

    const startDate = new Date(startDateTime);
    if (startDate.toDateString() !== targetDateStr) {
      continue;
    }
    const endDate = new Date(endDateTime);

    const startMinutes = startDate.getHours() * 60 + startDate.getMinutes();
    const endMinutes = endDate.getHours() * 60 + endDate.getMinutes();

    const top = (startMinutes - DAY_START_HOUR * 60) * PX_PER_MINUTE;
    const height = (endMinutes - startMinutes) * PX_PER_MINUTE;

    timedEvents.push({
      event,
      top,
      height,
      left: 0,
      width: 100,
    });
  }

  return { timedEvents };
};

export const CalendarGrid: React.FC<MultiDayCalendarGridProps> = ({
  hours,
  dates,
  events,
  loading,
  error,
  selectedCalendars,
  onEventClick,
  getEventColor,
  columnVirtualizer,
  isLoadingPast = false,
  isLoadingFuture = false,
}) => {
  const daysData = useMemo(
    () =>
      dates.map((date) => {
        const dayEvents = getEventPositions(events, date);
        return { date, ...dayEvents };
      }),
    [dates, events],
  );

  const hasAnyEvents = daysData.some((day) => day.timedEvents.length > 0);
  const totalWidth = columnVirtualizer.getTotalSize();

  return (
    <>
      <AllDayEventsSection
        events={events}
        dates={dates}
        onEventClick={onEventClick}
        getEventColor={getEventColor}
        columnVirtualizer={columnVirtualizer}
        totalWidth={totalWidth}
      />

      <div
        className="relative flex min-h-0 min-w-fit"
        style={{ height: `${hours.length * 64}px` }}
      >
        <CurrentTimeLine />

        <div
          className="sticky left-0 z-[11] w-20 flex-shrink-0 border-r border-zinc-800 bg-primary-bg"
          style={{ height: `${hours.length * 64}px` }}
        >
          <CurrentTimeLabel />

          {hours.map((hour) => (
            <div
              key={hour}
              className="flex h-16 items-start justify-end pt-2 pr-3"
            >
              <span className="text-xs text-zinc-500">
                {hour === 0
                  ? "12 AM"
                  : hour === 12
                    ? "12 PM"
                    : hour > 12
                      ? `${hour - 12} PM`
                      : `${hour} AM`}
              </span>
            </div>
          ))}
        </div>

        {/* Main Calendar Columns - Virtualized */}
        <div className="relative flex-1">
          <div
            className="relative"
            style={{
              width: `${columnVirtualizer.getTotalSize()}px`,
              height: `${hours.length * 64}px`,
            }}
          >
            {/* Full-height column borders for visible items */}
            <div
              className="pointer-events-none absolute top-0 left-0 flex"
              style={{ height: `${hours.length * 64}px` }}
            >
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

            {/* Loading overlay at left edge */}
            {isLoadingPast && columnVirtualizer.getVirtualItems()[0] && (
              <div
                className="absolute top-0 left-0 z-10 flex items-center justify-center bg-zinc-900/50"
                style={{
                  width: `${columnVirtualizer.getVirtualItems()[0].size}px`,
                  height: "100%",
                }}
              >
                <Spinner size="md" color="primary" />
              </div>
            )}

            {/* Virtualized Columns */}
            {columnVirtualizer.getVirtualItems().map((virtualColumn) => {
              const dayIndex = virtualColumn.index;
              const day = daysData[dayIndex];

              if (!day) return null;

              return (
                <div
                  key={virtualColumn.key}
                  className="absolute top-0 left-0"
                  style={{
                    width: `${virtualColumn.size}px`,
                    height: `${hours.length * 64}px`,
                    transform: `translateX(${virtualColumn.start}px)`,
                    scrollSnapAlign: "start",
                  }}
                >
                  <div className="relative h-full">
                    {/* Hour Dividers */}
                    {hours.map((hour) => (
                      <div
                        key={`divider-${hour}`}
                        className="h-16 border-t border-zinc-800 first:border-t-0"
                      />
                    ))}

                    {/* Events Container */}
                    <div className="absolute inset-0 px-2">
                      {day.timedEvents.map((eventPos) => {
                        const eventColor = getEventColor(eventPos.event);
                        return (
                          <button
                            type="button"
                            key={`event-${eventPos}`}
                            className="absolute ml-0.5 flex min-h-fit cursor-pointer overflow-hidden rounded-lg text-left text-white backdrop-blur-3xl transition-opacity duration-200 hover:opacity-80"
                            style={{
                              top: `${eventPos.top}px`,
                              height: `${eventPos.height}px`,
                              left: `${eventPos.left}%`,
                              width: `${eventPos.width - 1}%`,
                              backgroundColor: `${eventColor}40`,
                            }}
                            onClick={() => onEventClick?.(eventPos.event)}
                          >
                            <div
                              className="relative left-0 h-full min-h-full max-w-1 min-w-1 rounded-full"
                              style={{
                                backgroundColor: eventColor,
                              }}
                            />
                            <div className="p-3">
                              <div className="line-clamp-2 text-xs leading-tight font-medium">
                                {eventPos.event.summary}
                              </div>
                              {eventPos.event.start.dateTime &&
                                eventPos.event.end.dateTime && (
                                  <div className="mt-1 text-xs text-zinc-400">
                                    {formatEventTime(
                                      new Date(eventPos.event.start.dateTime),
                                    )}{" "}
                                    –{" "}
                                    {formatEventTime(
                                      new Date(eventPos.event.end.dateTime),
                                    )}
                                  </div>
                                )}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Loading overlay at right edge */}
            {isLoadingFuture && columnVirtualizer.getVirtualItems()[0] && (
              <div
                className="absolute top-0 right-0 z-10 flex items-center justify-center bg-zinc-900/50"
                style={{
                  width: `${columnVirtualizer.getVirtualItems()[0].size}px`,
                  height: "100%",
                }}
              >
                <Spinner size="md" color="primary" />
              </div>
            )}
          </div>
        </div>

        {/* Show message when no events on any day */}
        {!loading.calendars &&
          !loading.events &&
          !error.calendars &&
          !error.events &&
          selectedCalendars.length > 0 &&
          !hasAnyEvents && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center text-zinc-500">
                <div className="text-lg font-medium">No events scheduled</div>
                <div className="mt-1 text-sm">
                  for the selected day{dates.length > 1 ? "s" : ""}
                </div>
              </div>
            </div>
          )}
      </div>
    </>
  );
};
