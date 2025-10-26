import React, { useMemo } from "react";

import { GoogleCalendarIcon } from "@/components";
import { getEventColor } from "@/features/calendar/utils/eventColors";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { CalendarItem } from "@/types/api/calendarApiTypes";
import { GoogleCalendarEvent } from "@/types/features/calendarTypes";

interface UpcomingEventsViewProps {
  onEventClick?: (event: GoogleCalendarEvent) => void;
  events: GoogleCalendarEvent[];
  isFetching?: boolean;
  error?: string | null;
  calendars: CalendarItem[];
  // Connection state props
  isConnected?: boolean;
  onConnect?: (integrationId: string) => void;
  onRefresh?: () => void;
}

const UpcomingEventsView: React.FC<UpcomingEventsViewProps> = ({
  onEventClick,
  events,
  isFetching = false,
  error,
  calendars,
  isConnected = true,
  onConnect,
  onRefresh,
}) => {
  // Group all events by their date (show all events from API, grouped by day)
  const upcomingEventsByDay = useMemo(() => {
    const eventsByDay: { [key: string]: GoogleCalendarEvent[] } = {};
    events.forEach((event) => {
      // Prefer date (all-day) or dateTime (timed)
      let eventDate: string;
      if (event.start.date) {
        eventDate = event.start.date; // YYYY-MM-DD
      } else if (event.start.dateTime) {
        // Convert to local YYYY-MM-DD
        const d = new Date(event.start.dateTime);
        eventDate = d.toISOString().slice(0, 10);
      } else {
        return; // skip if no date
      }
      if (!eventsByDay[eventDate]) eventsByDay[eventDate] = [];
      eventsByDay[eventDate].push(event);
    });
    // Sort events within each day
    Object.values(eventsByDay).forEach((arr) =>
      arr.sort((a, b) => {
        const getSortDate = (ev: GoogleCalendarEvent) =>
          new Date(ev.start.dateTime || ev.start.date || "").getTime();
        return getSortDate(a) - getSortDate(b);
      }),
    );
    return eventsByDay;
  }, [events]);

  // Format time for display
  const formatTime = (startTime: string, endTime: string) => {
    const start = new Date(startTime);
    const end = new Date(endTime);

    const formatTimeString = (date: Date) => {
      const hours = date.getHours();
      const minutes = date.getMinutes();
      const ampm = hours >= 12 ? "PM" : "AM";
      const hour12 = hours % 12 || 12;
      const minuteStr = minutes.toString().padStart(2, "0");

      if (minutes === 0) {
        return `${hour12} ${ampm}`;
      }
      return `${hour12}:${minuteStr} ${ampm}`;
    };

    const startStr = formatTimeString(start);
    const endStr = formatTimeString(end);

    // Smart formatting - show AM/PM only when needed
    if (start.getHours() < 12 && end.getHours() >= 12)
      // Crossing from AM to PM
      return `${startStr} – ${endStr}`;
    else if (start.getHours() >= 12 && end.getHours() >= 12)
      // Both PM
      return `${startStr.replace(" PM", "")} – ${endStr}`;
    else if (start.getHours() < 12 && end.getHours() < 12)
      return `${startStr.replace(" AM", "")} – ${endStr}`;

    return `${startStr} – ${endStr}`;
  };

  // Check if an event has passed
  const isEventPassed = (event: GoogleCalendarEvent) => {
    const now = new Date();

    // For all-day events, check if the date has passed
    if (event.start.date && !event.start.dateTime) {
      const eventDate = new Date(event.start.date);
      eventDate.setHours(23, 59, 59, 999); // End of day
      return now > eventDate;
    }

    // For timed events, check if the end time has passed
    if (event.end.dateTime) {
      const eventEndTime = new Date(event.end.dateTime);
      return now > eventEndTime;
    }

    return false;
  };

  // Format date for display
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);

    if (date.toDateString() === today.toDateString()) {
      return "Today";
    } else if (date.toDateString() === tomorrow.toDateString()) {
      return "Tomorrow";
    } else {
      return date.toLocaleDateString("en-US", {
        weekday: "long",
        month: "long",
        day: "numeric",
      });
    }
  };

  const hasEvents = Object.keys(upcomingEventsByDay).length > 0;

  return (
    <BaseCardView
      title="Upcoming events"
      icon={<GoogleCalendarIcon className="h-5 w-5 text-zinc-500" />}
      isFetching={isFetching}
      error={error}
      isEmpty={!hasEvents}
      emptyMessage="No upcoming events"
      errorMessage="Failed to load upcoming events"
      isConnected={isConnected}
      connectIntegrationId="google_calendar"
      onConnect={onConnect}
      connectButtonText="Connect Calendar"
      path="/calendar"
      onRefresh={onRefresh}
    >
      <div className="space-y-6 p-4">
        {Object.entries(upcomingEventsByDay).map(
          ([dateString, events], index) => (
            <div key={dateString} className="flex gap-4">
              {/* Left Side - Date (20% width like 1 of 5 columns) */}
              <div className="w-1/5 flex-shrink-0">
                <div className="sticky top-0 z-10 px-2 pt-1">
                  <span
                    className={`text-sm ${index == 0 ? "text-primary" : "text-foreground-300"}`}
                  >
                    {formatDate(dateString)}
                  </span>
                </div>
              </div>

              {/* Right Side - Events (80% width like 4 of 5 columns) */}
              <div className="flex-1 space-y-2">
                {events.map((event) => {
                  const isPassed = isEventPassed(event);

                  return (
                    <div
                      key={event.id}
                      className="relative flex cursor-pointer items-start gap-2 rounded-lg p-2 pl-5 transition-colors hover:bg-zinc-700/30"
                      onClick={() => onEventClick?.(event)}
                      style={{
                        backgroundColor: `${getEventColor(event, calendars)}10`,
                      }}
                    >
                      {/* Colored Pill */}
                      <div className="absolute top-0 left-1 flex h-full items-center">
                        <div
                          className="mt-0.5 h-[80%] w-1 flex-shrink-0 rounded-full"
                          style={{
                            backgroundColor: getEventColor(event, calendars),
                            opacity: isPassed ? 0.5 : 1,
                          }}
                        />
                      </div>

                      {/* Event Details */}
                      <div className="min-w-0 flex-1">
                        {/* Title */}
                        <div
                          className={`text-base leading-tight font-medium ${isPassed ? "text-zinc-500" : "text-white"}`}
                        >
                          {event.summary}
                        </div>

                        {/* Time */}
                        <div
                          className={`mt-0.5 text-xs ${isPassed ? "text-zinc-600" : "text-zinc-400"}`}
                        >
                          {event.start.dateTime && event.end.dateTime
                            ? formatTime(
                                event.start.dateTime,
                                event.end.dateTime,
                              )
                            : "All day"}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ),
        )}
      </div>
    </BaseCardView>
  );
};

export default UpcomingEventsView;
