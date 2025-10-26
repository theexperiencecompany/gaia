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
  currentTimeTop?: number;
  currentTimeLabel?: string;
  columnWidth: number;
  isLoadingPast?: boolean;
  isLoadingFuture?: boolean;
}

const PX_PER_MINUTE = 64 / 60;
const DAY_START_HOUR = 0;

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

export const CalendarGrid: React.FC<MultiDayCalendarGridProps> = ({
  hours,
  dates,
  events,
  loading,
  error,
  selectedCalendars,
  onEventClick,
  getEventColor,
  currentTimeTop,
  currentTimeLabel,
  columnWidth,
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

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col">
      <AllDayEventsSection
        events={events}
        dates={dates}
        onEventClick={onEventClick}
        getEventColor={getEventColor}
        columnWidth={columnWidth}
      />

      <div className="relative flex min-h-0 min-w-fit flex-1">
        {/* Global loading overlay for initial/main loading */}
        {loading.events && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-zinc-900/50">
            <Spinner size="lg" color="primary" />
          </div>
        )}

        {/* Global error states */}
        {error.calendars && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-zinc-900/80">
            <div className="text-center text-red-500">
              <div className="text-lg font-medium">Error loading calendars</div>
              <div className="mt-1 text-sm">{error.calendars}</div>
            </div>
          </div>
        )}

        {error.events && !loading.events && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-zinc-900/80">
            <div className="text-center text-red-500">
              <div className="text-lg font-medium">Error loading events</div>
              <div className="mt-1 text-sm">{error.events}</div>
            </div>
          </div>
        )}

        {selectedCalendars.length === 0 && !loading.calendars && (
          <div className="absolute inset-0 z-20 flex items-center justify-center">
            <div className="text-center text-zinc-500">
              <div className="text-lg font-medium">No calendars selected</div>
              <div className="mt-1 text-sm">
                Please select a calendar to view events
              </div>
            </div>
          </div>
        )}
        {/* Full-height column borders */}
        <div
          className="pointer-events-none absolute top-0 left-20 flex"
          style={{ height: `${hours.length * 64}px` }}
        >
          {daysData.map((day, dayIndex) => (
            <div
              key={`border-${dayIndex}`}
              className="h-full flex-shrink-0 border-r border-zinc-800 last:border-r-0"
              style={{ width: `${columnWidth}px` }}
            />
          ))}
        </div>

        {/* Current Time Line & Label */}
        {typeof currentTimeTop === "number" && currentTimeLabel && (
          <>
            {/* Blue horizontal line across all columns */}
            <div
              className="absolute right-0 left-20 z-[1] h-[1px] bg-primary/50"
              style={{ top: `${currentTimeTop}px` }}
            />
          </>
        )}

        {/* Time Labels Column */}
        <div
          className="sticky left-0 z-[11] w-20 flex-shrink-0 border-r border-zinc-800 bg-[#1a1a1a]"
          style={{ height: `${hours.length * 64}px` }}
        >
          {/* Current Time Line & Label */}
          {typeof currentTimeTop === "number" && currentTimeLabel && (
            <div
              className="absolute left-0 z-[12] flex w-20 flex-shrink-0 items-center justify-end bg-[#1a1a1a] pr-3 text-xs text-primary"
              style={{ top: `${currentTimeTop - 8}px` }}
            >
              {currentTimeLabel}
            </div>
          )}

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

        {/* Main Calendar Columns for each day */}
        <div className="relative flex flex-1">
          {/* Loading overlay at left edge */}
          {isLoadingPast && (
            <div
              className="absolute top-0 left-0 z-10 flex items-center justify-center bg-zinc-900/50"
              style={{ width: `${columnWidth}px`, height: "100%" }}
            >
              <Spinner size="md" color="primary" />
            </div>
          )}
          {daysData.map((day, dayIndex) => {
            return (
              <div
                key={dayIndex}
                className="relative flex-shrink-0"
                style={{
                  width: `${columnWidth}px`,
                  scrollSnapAlign: "start",
                }}
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
                  {/* Only render events, no per-column loading states */}
                  {day.timedEvents.map((eventPos, eventIndex) => {
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
                  })}
                </div>
              </div>
            );
          })}

          {/* Loading overlay at right edge */}
          {isLoadingFuture && (
            <div
              className="absolute top-0 right-0 z-10 flex items-center justify-center bg-zinc-900/50"
              style={{ width: `${columnWidth}px`, height: "100%" }}
            >
              <Spinner size="md" color="primary" />
            </div>
          )}
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
    </div>
  );
};
