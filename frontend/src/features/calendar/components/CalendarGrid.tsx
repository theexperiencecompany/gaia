"use client";

import { Spinner } from "@heroui/react";
import React, { forwardRef, useMemo } from "react";

import { AllDayEventsSection } from "@/features/calendar/components/AllDayEventsSection";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

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
}

const PX_PER_MINUTE = 64 / 60;
const DAY_START_HOUR = 0;

const timeToMinutes = (time: string): number => {
  const [hours, minutes] = time.split(":").map(Number);
  return hours * 60 + minutes;
};

const getEventPositions = (events: GoogleCalendarEvent[], targetDate: Date) => {
  const targetDateStr = targetDate.toDateString();

  const timedEvents = events
    .filter((event) => {
      const eventDateStr = event.start.dateTime
        ? new Date(event.start.dateTime).toDateString()
        : null;
      return eventDateStr === targetDateStr && event.start.dateTime;
    })
    .map((event) => {
      const startTime = new Date(event.start.dateTime!);
      const endTime = new Date(event.end.dateTime!);

      const startMinutes = startTime.getHours() * 60 + startTime.getMinutes();
      const endMinutes = endTime.getHours() * 60 + endTime.getMinutes();

      const top = (startMinutes - DAY_START_HOUR * 60) * PX_PER_MINUTE;
      const height = (endMinutes - startMinutes) * PX_PER_MINUTE;

      return {
        event,
        top,
        height,
        left: 0,
        width: 100,
      };
    });

  return { timedEvents };
};

export const CalendarGrid = forwardRef<
  HTMLDivElement,
  MultiDayCalendarGridProps
>(
  (
    {
      hours,
      dates,
      events,
      loading,
      error,
      selectedCalendars,
      onEventClick,
      getEventColor,
    },
    ref,
  ) => {
    const daysData = useMemo(
      () =>
        dates.map((date) => {
          const dayEvents = getEventPositions(events, date);
          return { date, ...dayEvents };
        }),
      [dates, events],
    );

    const hasAnyEvents = daysData.some((day) => day.timedEvents.length > 0);

    return (
      <div className="relative flex-1 overflow-y-auto" ref={ref}>
        <AllDayEventsSection
          events={events}
          dates={dates}
          onEventClick={onEventClick}
          getEventColor={getEventColor}
        />

        <div className="relative flex">
          {/* Time Labels Column */}
          <div className="w-20 flex-shrink-0 border-r border-zinc-800">
            {hours.map((hour) => (
              <div
                key={hour}
                className="flex h-16 items-start justify-end pt-2 pr-3"
              >
                <span className="text-xs font-medium text-zinc-500">
                  {hour === 0
                    ? "12AM"
                    : hour === 12
                      ? "12PM"
                      : hour > 12
                        ? `${hour - 12}PM`
                        : `${hour}AM`}
                </span>
              </div>
            ))}
          </div>

          {/* Main Calendar Columns for each day */}
          <div className="relative flex flex-1">
            {daysData.map((day, dayIndex) => (
              <div
                key={dayIndex}
                className="relative flex-1 border-r border-zinc-800 last:border-r-0"
              >
                {/* Hour Dividers */}
                {hours.map((hour) => (
                  <div
                    key={`divider-${hour}`}
                    className="h-16 border-t border-zinc-800 first:border-t-0"
                  />
                ))}

                {/* Events Container */}
                <div className="absolute inset-0 px-2">
                  {loading.calendars ? (
                    <div className="flex h-full items-center justify-center">
                      <Spinner size="lg" color="default" />
                    </div>
                  ) : error.calendars ? (
                    <div className="flex h-full items-center justify-center">
                      <div className="text-center text-red-500">
                        <div className="text-lg font-medium">
                          Error loading calendars
                        </div>
                        <div className="mt-1 text-sm">{error.calendars}</div>
                      </div>
                    </div>
                  ) : selectedCalendars.length === 0 ? (
                    <div className="flex h-full items-center justify-center">
                      <div className="text-center text-zinc-500">
                        <div className="text-lg font-medium">
                          No calendars selected
                        </div>
                        <div className="mt-1 text-sm">
                          Please select a calendar to view events
                        </div>
                      </div>
                    </div>
                  ) : loading.events ? (
                    <div className="flex h-full items-center justify-center">
                      <Spinner size="lg" color="default" />
                    </div>
                  ) : error.events ? (
                    <div className="flex h-full items-center justify-center">
                      <div className="text-center text-red-500">
                        <div className="text-lg font-medium">
                          Error loading events
                        </div>
                        <div className="mt-1 text-sm">{error.events}</div>
                      </div>
                    </div>
                  ) : day.timedEvents.length === 0 ? null : (
                    day.timedEvents.map((eventPos, eventIndex) => {
                      const eventColor = getEventColor(eventPos.event);
                      return (
                        <div
                          key={`event-${eventIndex}`}
                          className="absolute ml-0.5 flex min-h-fit cursor-pointer overflow-hidden rounded-lg text-white backdrop-blur-3xl transition-all duration-200 hover:opacity-80"
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
                                  {new Date(
                                    eventPos.event.start.dateTime,
                                  ).toLocaleTimeString("en-US", {
                                    hour: "numeric",
                                    minute: "2-digit",
                                    hour12: true,
                                  })}{" "}
                                  –{" "}
                                  {new Date(
                                    eventPos.event.end.dateTime,
                                  ).toLocaleTimeString("en-US", {
                                    hour: "numeric",
                                    minute: "2-digit",
                                    hour12: true,
                                  })}
                                </div>
                              )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            ))}
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
    );
  },
);

CalendarGrid.displayName = "CalendarGrid";
