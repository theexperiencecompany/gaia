"use client";

import { Spinner } from "@heroui/react";
import React, { forwardRef } from "react";

import { EventPosition } from "@/features/calendar/hooks/useCalendarEventPositioning";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface CalendarGridProps {
  hours: number[];
  dayEvents: EventPosition[];
  loading: {
    calendars: boolean;
    events: boolean;
  };
  error: {
    calendars: string | null;
    events: string | null;
  };
  selectedCalendars: string[];
  selectedDate: Date;
  onEventClick?: (event: GoogleCalendarEvent) => void;
  getEventColor: (event: GoogleCalendarEvent) => string;
}

export const CalendarGrid = forwardRef<HTMLDivElement, CalendarGridProps>(
  (
    {
      hours,
      dayEvents,
      loading,
      error,
      selectedCalendars,
      selectedDate,
      onEventClick,
      getEventColor,
    },
    ref,
  ) => {
    return (
      <div className="flex-1 overflow-y-auto" ref={ref}>
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

          {/* Main Calendar Column */}
          <div className="relative flex-1">
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
              ) : dayEvents.length === 0 ? (
                <div className="flex h-full items-center justify-center">
                  <div className="text-center text-zinc-500">
                    <div className="text-lg font-medium">
                      No events scheduled
                    </div>
                    <div className="mt-1 text-sm">
                      for{" "}
                      {selectedDate.toLocaleDateString("en-US", {
                        weekday: "long",
                        month: "long",
                        day: "numeric",
                      })}
                    </div>
                  </div>
                </div>
              ) : (
                dayEvents.map((eventPos, eventIndex) => {
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
                        // backgroundColor: eventColor,
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
                        <div className="line-clamp-2 text-sm leading-tight font-medium">
                          {eventPos.event.summary}
                        </div>
                        {eventPos.event.start.dateTime &&
                          eventPos.event.end.dateTime && (
                            <div className="mt-1 text-xs text-white/80">
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
        </div>
      </div>
    );
  },
);

CalendarGrid.displayName = "CalendarGrid";
