import {
  bucketDate,
  formatDateWithRelative,
  formatTimeRange,
} from "@gaia/shared";
import { ScrollShadow } from "@heroui/scroll-shadow";
import type { CalendarOptions } from "@/types/features/calendarTypes";

import { EventCard } from "./CalendarEventCard";

interface CalendarEventReadonlySectionProps {
  calendar_options: CalendarOptions[];
}

const DEFAULT_EVENT_COLOR = "#00bbff";

function eventTimeDisplay(option: CalendarOptions): string {
  if (option.start?.includes("T") && option.end?.includes("T")) {
    return formatTimeRange(option.start, option.end);
  }
  if (option.is_all_day) return "All day";
  return option.start ?? "All day";
}

/**
 * Read-only render of a legacy create-event proposal restored from history.
 * The interactive add flow moved to HIL approvals; this only replays what an
 * older conversation already showed, so it carries no confirm action.
 */
export function CalendarEventReadonlySection({
  calendar_options,
}: CalendarEventReadonlySectionProps) {
  const events = calendar_options.filter((option) => option.summary);
  if (events.length === 0) return null;

  const eventsByDate: Record<string, CalendarOptions[]> = {};
  for (const option of events) {
    const date = bucketDate(option.start ?? new Date().toISOString());
    const dayEvents = eventsByDate[date] ?? [];
    dayEvents.push(option);
    eventsByDate[date] = dayEvents;
  }

  return (
    <div className="w-full max-w-md rounded-3xl bg-zinc-800 p-4 text-white">
      <ScrollShadow className="mt-2 max-h-[400px] space-y-3">
        {Object.entries(eventsByDate).map(([dateString, dayEvents]) => (
          <div key={dateString} className="space-y-3">
            <div className="relative flex items-center">
              <div className="flex-1 border-t border-zinc-700" />
              <span className="px-3 text-xs text-zinc-500">
                {formatDateWithRelative(dateString)}
              </span>
              <div className="flex-1 border-t border-zinc-700" />
            </div>

            <div className="space-y-2">
              {dayEvents.map((option) => (
                <EventCard
                  key={`${option.summary}:${option.start ?? ""}:${option.end ?? ""}`}
                  eventColor={option.background_color || DEFAULT_EVENT_COLOR}
                  variant="display"
                >
                  <div className="text-base leading-tight text-white">
                    {option.summary}
                  </div>
                  {option.description && (
                    <div className="mt-1 text-xs text-zinc-400">
                      {option.description}
                    </div>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-zinc-400">
                    <span>{eventTimeDisplay(option)}</span>
                    {option.calendar_name && (
                      <span>{option.calendar_name}</span>
                    )}
                    {option.attendees && option.attendees.length > 0 && (
                      <span>
                        {option.attendees.length}
                        {option.attendees.length === 1 ? " guest" : " guests"}
                      </span>
                    )}
                  </div>
                </EventCard>
              ))}
            </div>
          </div>
        ))}
      </ScrollShadow>
    </div>
  );
}
