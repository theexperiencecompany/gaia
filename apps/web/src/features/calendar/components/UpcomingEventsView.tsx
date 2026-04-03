"use client";

import {
  Alert01Icon,
  Brain02Icon,
  CalendarUpload01Icon,
  ChartLineData01Icon,
  Edit02Icon,
  Mail01Icon,
  Target02Icon,
} from "@icons";
import type React from "react";
import { useMemo } from "react";
import { GoogleCalendarIcon } from "@/components/shared/icons";
import { getEventColor } from "@/features/calendar/utils/eventColors";
import type { CardAction } from "@/features/chat/components/interface/BaseCardView";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { useAppendToInput } from "@/stores/composerStore";
import type { CalendarItem } from "@/types/api/calendarApiTypes";
import type { GoogleCalendarEvent } from "@/types/features/calendarTypes";
import { formatDate } from "@/utils/date/dateUtils";

interface UpcomingEventsViewProps {
  onEventClick?: (event: GoogleCalendarEvent) => void;
  events?: GoogleCalendarEvent[];
  calendars?: CalendarItem[];
  isConnected?: boolean;
  onConnect?: (integrationId: string) => void;
}

const UpcomingEventsView: React.FC<UpcomingEventsViewProps> = ({
  onEventClick,
  events = [],
  calendars = [],
  isConnected = true,
  onConnect,
}) => {
  const appendToInput = useAppendToInput();

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
    const getSortDate = (ev: GoogleCalendarEvent) =>
      new Date(ev.start.dateTime || ev.start.date || "").getTime();
    Object.values(eventsByDay).forEach((arr) =>
      arr.sort((a, b) => getSortDate(a) - getSortDate(b)),
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

  const hasEvents = Object.keys(upcomingEventsByDay).length > 0;

  const actions: CardAction[] = useMemo(
    () => [
      {
        key: "brief-today",
        label: "Brief me on today",
        description:
          "Get context on each meeting — attendees, history, prep needed",
        icon: <Brain02Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Give me a briefing for each of my meetings today. For each one, tell me who's attending, what we discussed last time if applicable, and what I should prepare or know before going in.",
          ),
      },
      {
        key: "prep-next-meeting",
        label: "Prep next meeting",
        description: "Generate an agenda and talking points for my next event",
        icon: <Edit02Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Look at my next upcoming calendar event and generate a structured agenda with talking points and any questions I should raise.",
          ),
      },
      {
        key: "async-candidates",
        label: "Which meetings can be emails?",
        description: "Identify low-value meetings and draft async alternatives",
        icon: <Mail01Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Review my upcoming meetings and identify which ones could be replaced with a short email or async update instead. For each candidate, draft the async message.",
          ),
      },
      {
        key: "focus-blocks",
        label: "Find focus blocks",
        description: "Spot gaps in my calendar and suggest deep-work slots",
        icon: <Target02Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Look at my calendar for the next 7 days and identify the best gaps where I could block time for focused, deep work. Suggest specific slots with reasoning.",
          ),
      },
      {
        key: "conflicts",
        label: "Detect back-to-backs",
        description:
          "Flag days with no breathing room and suggest what to reschedule",
        icon: <Alert01Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Check my upcoming calendar for days with back-to-back meetings or no breaks. Flag the worst days and suggest which meetings I could move or decline.",
          ),
      },
      {
        key: "last-week-recap",
        label: "Summarise last week",
        description:
          "Recap everything discussed in meetings over the past 7 days",
        icon: <ChartLineData01Icon className="size-4 text-zinc-400" />,
        onPress: () =>
          appendToInput(
            "Summarise everything I discussed and decided in my meetings over the past 7 days. Give me a concise recap by day.",
          ),
      },
    ],
    [appendToInput],
  );

  return (
    <BaseCardView
      title="Upcoming events"
      icon={<CalendarUpload01Icon className="h-6 w-6 text-zinc-500" />}
      isEmpty={!hasEvents}
      emptyMessage="No upcoming events"
      errorMessage="Failed to load upcoming events"
      isConnected={isConnected}
      connectIntegrationId="googlecalendar"
      onConnect={onConnect}
      connectButtonText="Connect"
      connectTitle="Connect Your Calendar"
      connectDescription="Manage events and view your schedule"
      connectIcon={<GoogleCalendarIcon width={32} height={32} />}
      actions={actions}
    >
      <div className="space-y-6 p-4">
        {Object.entries(upcomingEventsByDay).map(
          ([dateString, events], index) => (
            <div key={dateString} className="flex gap-4">
              {/* Left Side - Date (20% width like 1 of 5 columns) */}
              <div className="w-1/5 flex-shrink-0">
                <div className="sticky top-0 z-10 px-2 pt-1">
                  <span
                    className={`text-sm ${index === 0 ? "text-primary" : "text-foreground-300"}`}
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
