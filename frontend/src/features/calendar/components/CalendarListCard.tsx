import { ScrollShadow } from "@heroui/scroll-shadow";

import { GoogleCalendarIcon } from "@/components";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { CalendarFetchData } from "@/types/features/calendarTypes";

interface CalendarListProps {
  events?: CalendarFetchData[] | null;
  isCollapsible?: boolean;
}

function formatTime(time: string | null): string {
  if (!time) return "";

  try {
    const date = new Date(time);

    // Check if it's a date-only format (YYYY-MM-DD)
    if (time.includes("T")) {
      // DateTime format - show date and time
      return date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
    } else {
      // Date-only format - show just the date
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
    }
  } catch {
    return time; // Return original string if parsing fails
  }
}

export default function CalendarListCard({
  events,
  isCollapsible = true,
}: CalendarListProps) {
  if (!!events && events.length > 0) {
    const content = (
      <div className="mt-3 w-full max-w-2xl rounded-3xl bg-zinc-800 p-3 text-white">
        <ScrollShadow className="mt-2 max-h-[300px] space-y-1 divide-y divide-gray-700">
          {events.map((event, index) => (
            <div
              key={index}
              className="group grid grid-cols-5 items-center justify-evenly gap-4 rounded-lg p-2 transition-colors hover:bg-zinc-700"
            >
              <div className="col-span-3">
                <span className="block truncate text-sm font-medium text-gray-300">
                  {event.summary}
                </span>
              </div>

              <div className="">
                <span className="block truncate text-sm text-white group-hover:text-gray-100">
                  {event.calendar_name || "Default Calendar"}
                </span>
              </div>

              <div className="text-right">
                <span className="text-xs text-nowrap text-gray-400">
                  {formatTime(event.start_time)}
                </span>
              </div>
            </div>
          ))}
        </ScrollShadow>
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
