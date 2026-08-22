import { Button } from "@heroui/button";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { CalendarAdd01Icon, Tick02Icon } from "@icons";
import { useMemo, useState } from "react";
import { calendarApi } from "@/features/calendar/api/calendarApi";
import { getBrowserTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";
import type {
  CalendarEvent,
  SameDayEvent,
  SingleTimeEvent,
  TimedEvent,
} from "@/types/features/calendarTypes";
import type { CalendarOptions } from "@/types/features/convoTypes";
import { buildAddEventPayload } from "@/utils/calendar/eventPayloadBuilders";
import {
  formatDateWithRelative,
  formatTimeRange,
} from "@/utils/date/calendarDateUtils";

import { EventCard } from "./CalendarEventCard";
import { EventContent } from "./CalendarEventContent";

type EventStatus = "idle" | "loading" | "completed";

// Built once at module scope; identical output to calling
// date.toLocaleTimeString("en-US", …) per render. The explicit timeZone keeps
// formatting deterministic across server and browser (off-screen it resolves
// to the browser's own zone, matching implicit local formatting).
const SINGLE_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: getBrowserTimezone(),
});

function getDisplayTime(event: CalendarEvent | SameDayEvent): string {
  if ("start" in event && typeof event.start === "object") {
    const sameDayEvent = event as SameDayEvent;
    if (sameDayEvent.start?.dateTime && sameDayEvent.end?.dateTime) {
      return formatTimeRange(
        sameDayEvent.start.dateTime,
        sameDayEvent.end.dateTime,
      );
    }
    if (sameDayEvent.start?.date) return "All day";
    return "No time";
  }

  const calEvent = event as CalendarEvent;
  if ("start" in calEvent && "end" in calEvent && calEvent.start) {
    const timedEvent = calEvent as TimedEvent;
    const startStr = timedEvent.start;
    const endStr = timedEvent.end;
    if (startStr?.includes("T") && endStr?.includes("T")) {
      return formatTimeRange(startStr, endStr);
    }
    return "All day";
  }

  if ("time" in calEvent && calEvent.time) {
    const singleTimeEvent = calEvent as SingleTimeEvent;
    if (singleTimeEvent.time.includes("T")) {
      return SINGLE_TIME_FORMATTER.format(new Date(singleTimeEvent.time));
    }
    return "All day";
  }

  return "No time";
}

export default function CalendarEventSection({
  calendar_options,
}: {
  calendar_options: CalendarOptions[];
}) {
  const [eventStatuses, setEventStatuses] = useState<EventStatus[]>([]);
  const [isConfirmingAll, setIsConfirmingAll] = useState(false);

  const same_day_events = calendar_options[0]?.same_day_events;

  const calendarEvents: CalendarEvent[] = useMemo(
    () =>
      calendar_options.map((option): CalendarEvent => {
        if (option.start && option.end) {
          const timedEvent: TimedEvent = {
            summary: option.summary,
            description: option.description || "",
            start: option.start,
            end: option.end,
            is_all_day: option.is_all_day || false,
            recurrence: option.recurrence,
            calendar_id: option.calendar_id,
            attendees: option.attendees,
            create_meeting_room: option.create_meeting_room,
          };
          return timedEvent;
        }

        if (option.start) {
          const singleTimeEvent: SingleTimeEvent = {
            summary: option.summary,
            description: option.description || "",
            time: option.start,
            is_all_day: option.is_all_day ?? true,
            recurrence: option.recurrence,
            calendar_id: option.calendar_id,
            attendees: option.attendees,
            create_meeting_room: option.create_meeting_room,
          };
          return singleTimeEvent;
        }

        const fallbackEvent: SingleTimeEvent = {
          summary: option.summary,
          description: option.description || "",
          time: "Time TBD",
          is_all_day: true,
          recurrence: option.recurrence,
          calendar_id: option.calendar_id,
          attendees: option.attendees,
          create_meeting_room: option.create_meeting_room,
        };
        return fallbackEvent;
      }),
    [calendar_options],
  );

  // Group events by date, including same-day events
  const eventsByDate = useMemo(() => {
    const grouped: Record<
      string,
      Array<{
        event: CalendarEvent | SameDayEvent;
        index?: number;
        isSameDay?: boolean;
      }>
    > = {};

    // Add same-day events
    same_day_events?.forEach((event) => {
      const dateStr =
        event.start?.dateTime || event.start?.date || new Date().toISOString();
      const date = new Date(dateStr).toISOString().slice(0, 10);
      if (!grouped[date]) grouped[date] = [];
      grouped[date].push({ event, isSameDay: true });
    });

    // Add new events
    calendarEvents.forEach((event, index) => {
      let dateStr: string;
      if ("start" in event && event.start) {
        dateStr = event.start;
      } else if ("time" in event && event.time) {
        dateStr = event.time;
      } else {
        dateStr = new Date().toISOString();
      }
      const date = new Date(dateStr).toISOString().slice(0, 10);
      if (!grouped[date]) grouped[date] = [];
      grouped[date].push({ event, index, isSameDay: false });
    });

    // Sort events within each day
    const getTime = (e: CalendarEvent | SameDayEvent) => {
      if ("start" in e && typeof e.start === "object") {
        return new Date(e.start.dateTime || e.start.date || 0).getTime();
      }
      if ("start" in e && typeof e.start === "string") {
        return new Date(e.start).getTime();
      }
      if ("time" in e) {
        return new Date(e.time).getTime();
      }
      return 0;
    };
    Object.values(grouped).forEach((dayEvents) => {
      dayEvents.sort((a, b) => getTime(a.event) - getTime(b.event));
    });

    return grouped;
  }, [calendarEvents, same_day_events]);

  if (!calendar_options.every((option) => option.summary)) {
    return (
      <div className="p-3 text-red-500">
        Error: Could not add Calendar event. Please try again later.
      </div>
    );
  }

  const handleAdd = async (event: CalendarEvent, index: number) => {
    // Index-assign (not slice-splice): slice() drops leading gaps, so an
    // out-of-order first click would append at the wrong position and
    // permanently misalign statuses with events. Pure-expression updater —
    // no statements inside the state setter.
    const setStatusAt = (status: EventStatus) =>
      setEventStatuses((prev) =>
        Object.assign([...prev], { [index]: status as EventStatus }),
      );
    try {
      setStatusAt("loading");
      await calendarApi.createEventDefault(buildAddEventPayload(event));
      setStatusAt("completed");
    } catch (error) {
      console.error("Error adding event:", error);
      setStatusAt("idle");
      toast.error("Failed to add event");
    }
  };

  const handleAddAll = async () => {
    setIsConfirmingAll(true);
    const pendingEvents: Array<{ event: CalendarEvent; index: number }> = [];
    for (const [index, event] of calendarEvents.entries()) {
      if (eventStatuses[index] !== "completed") {
        pendingEvents.push({ event, index });
      }
    }

    try {
      await Promise.all(
        pendingEvents.map(({ event, index }) => handleAdd(event, index)),
      );
    } catch (error) {
      console.error("Error adding events:", error);
      toast.error("Failed to add all events");
    } finally {
      setIsConfirmingAll(false);
    }
  };

  // Statuses are only recorded for indexes inside calendar_events, so equal
  // counts imply every event reached "completed". The length pre-checks also
  // bail out before .every()/.some() walk the events.
  // js-length-check-first: array comparison must lead with the shared length
  // equality so mismatched sizes bail out before item-by-item .every().
  const allCompleted =
    calendarEvents.length === eventStatuses.length &&
    calendarEvents.every((_, index) => eventStatuses[index] === "completed");

  const hasCompletedEvents =
    calendarEvents.length > 0 &&
    calendarEvents.some((_, index) => eventStatuses[index] === "completed");

  return (
    <div className="w-full max-w-md rounded-3xl bg-zinc-800 p-4 text-white">
      <ScrollShadow className="mt-2 max-h-[400px] space-y-3">
        {Object.entries(eventsByDate).map(([dateString, events]) => (
          <div key={dateString} className="space-y-3">
            <div className="relative flex items-center">
              <div className="flex-1 border-t border-zinc-700" />
              <span className="px-3 text-xs text-zinc-500">
                {formatDateWithRelative(dateString)}
              </span>
              <div className="flex-1 border-t border-zinc-700" />
            </div>

            <div className="space-y-2">
              {events.map(({ event, index, isSameDay }) => {
                if (isSameDay) {
                  const sameDayEvent = event as SameDayEvent;
                  const eventColor = sameDayEvent.background_color || "#00bbff";
                  return (
                    <div
                      key={`same-${sameDayEvent.id}`}
                      className="relative flex items-start gap-2 rounded-lg p-3 pl-5 transition-colors hover:bg-zinc-700/50"
                      style={{ backgroundColor: `${eventColor}20` }}
                    >
                      <div className="absolute top-0 left-1 flex h-full items-center">
                        <div
                          className="h-[80%] w-1 flex-shrink-0 rounded-full"
                          style={{ backgroundColor: eventColor }}
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-base leading-tight text-white">
                          {sameDayEvent.summary}
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
                          <span>{getDisplayTime(sameDayEvent)}</span>
                          {sameDayEvent.calendarTitle && (
                            <>
                              <span className="text-zinc-500">•</span>
                              <span>{sameDayEvent.calendarTitle}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                }

                const status = eventStatuses[index!] || "idle";
                // Get background_color from the original calendar_option
                const originalOption = calendar_options[index!];
                const eventColor =
                  originalOption?.background_color || "#00bbff";

                return (
                  <EventCard
                    key={index}
                    eventColor={eventColor}
                    status={status}
                    variant="action"
                    buttonColor="primary"
                    completedLabel="Added"
                    icon={CalendarAdd01Icon}
                    onAction={() => handleAdd(event as CalendarEvent, index!)}
                  >
                    <EventContent event={event as CalendarEvent} />
                  </EventCard>
                );
              })}
            </div>
          </div>
        ))}
      </ScrollShadow>

      {calendarEvents.length > 1 && (
        <Button
          className="mt-3"
          color="primary"
          variant="solid"
          fullWidth
          isDisabled={allCompleted}
          isLoading={isConfirmingAll}
          onPress={handleAddAll}
        >
          {allCompleted ? (
            <>
              <Tick02Icon width={22} />
              All Added
            </>
          ) : hasCompletedEvents ? (
            "Add Remaining"
          ) : (
            "Add All Events"
          )}
        </Button>
      )}
    </div>
  );
}
