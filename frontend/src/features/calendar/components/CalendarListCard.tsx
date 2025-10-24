import { Button } from "@heroui/button";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { GoogleCalendarIcon } from "@/components";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { CalendarFetchData } from "@/types/features/calendarTypes";
import {
  formatDateWithRelative,
  formatTimeRange,
} from "@/utils/date/calendarDateUtils";

interface CalendarListProps {
  events?: CalendarFetchData[] | null;
  isCollapsible?: boolean;
}

export default function CalendarListCard({
  events,
  isCollapsible = true,
}: CalendarListProps) {
  const router = useRouter();

  // Group events by date
  const eventsByDay = useMemo(() => {
    if (!events) return {};

    const grouped: { [key: string]: CalendarFetchData[] } = {};
    events.forEach((event) => {
      // Extract date from start_time
      let eventDate: string;
      if (event.start_time.includes("T")) {
        // DateTime - convert to local YYYY-MM-DD
        const d = new Date(event.start_time);
        eventDate = d.toISOString().slice(0, 10);
      } else {
        // Date-only format
        eventDate = event.start_time;
      }

      if (!grouped[eventDate]) {
        grouped[eventDate] = [];
      }
      grouped[eventDate].push(event);
    });

    // Sort events within each day
    Object.values(grouped).forEach((dayEvents) =>
      dayEvents.sort((a, b) => {
        const aTime = new Date(a.start_time).getTime();
        const bTime = new Date(b.start_time).getTime();
        return aTime - bTime;
      }),
    );

    return grouped;
  }, [events]);

  if (!!events && events.length > 0) {
    const content = (
      <div className="w-full max-w-md rounded-3xl bg-zinc-800 p-4 text-white">
        <ScrollShadow className="mt-2 max-h-[400px] space-y-3">
          {Object.entries(eventsByDay).map(([dateString, dayEvents]) => (
            <div key={dateString} className="space-y-3">
              <div className="relative flex items-center">
                <div className="flex-1 border-t border-zinc-700" />
                <span className="px-3 text-xs text-zinc-500">
                  {formatDateWithRelative(dateString)}
                </span>
                <div className="flex-1 border-t border-zinc-700" />
              </div>

              <div className="space-y-2">
                {dayEvents.map((event, index) => {
                  const eventColor = event.background_color || "#00bbff";

                  return (
                    <div
                      key={index}
                      className="relative flex items-start gap-2 rounded-lg p-3 pl-5 transition-colors hover:bg-zinc-700/50"
                      style={{
                        backgroundColor: `${eventColor}20`,
                      }}
                    >
                      {/* Colored left border pill */}
                      <div className="absolute top-0 left-1 flex h-full items-center">
                        <div
                          className="h-[80%] w-1 flex-shrink-0 rounded-full"
                          style={{
                            backgroundColor: eventColor,
                          }}
                        />
                      </div>

                      {/* Event Details */}
                      <div className="min-w-0 flex-1">
                        {/* Title */}
                        <div className="text-base leading-tight text-white">
                          {event.summary}
                        </div>

                        {/* Time and Calendar Name */}
                        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-400">
                          <span>
                            {event.start_time.includes("T") && event.end_time
                              ? formatTimeRange(
                                  event.start_time,
                                  event.end_time,
                                )
                              : "All day"}
                          </span>
                          {event.calendar_name && (
                            <>
                              <span className="text-zinc-500">•</span>
                              <span className="text-zinc-400">
                                {event.calendar_name}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </ScrollShadow>

        <Button
          onPress={() => router.push("/calendar")}
          color="primary"
          className="mt-3 text-primary"
          fullWidth
          variant="flat"
        >
          Open Calendar
        </Button>
      </div>
    );

    return (
      <CollapsibleListWrapper
        icon={<GoogleCalendarIcon width={20} height={20} />}
        count={events.length}
        label="Event"
        isCollapsible={isCollapsible}
      >
        {content}
      </CollapsibleListWrapper>
    );
  }
}
