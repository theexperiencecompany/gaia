import { ScrollShadow } from "@heroui/scroll-shadow";

import { GoogleCalendarIcon } from "@/components/shared/icons";
import type { CalendarListFetchData } from "@/types/features/calendarTypes";

interface CalendarListFetchProps {
  calendars?: CalendarListFetchData[] | null;
}

export default function CalendarListFetchCard({
  calendars,
}: CalendarListFetchProps) {
  if (calendars && calendars.length > 0)
    return (
      <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-3 text-white">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-1">
          <div className="flex items-center gap-2">
            <GoogleCalendarIcon width={20} height={20} />
            <span className="text-sm font-medium">
              Fetched {calendars.length} Calendar
              {calendars.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>

        <ScrollShadow className="max-h-[200px] overflow-x-hidden">
          <div className="divide-y divide-zinc-800">
            {calendars.length > 0 &&
              calendars
                .toSorted((a, b) => a.name.localeCompare(b.name)) // Sort alphabetically
                .map((calendar) => (
                  <div
                    key={calendar.id}
                    className="group flex items-center gap-3 p-3 transition-colors hover:bg-zinc-700"
                  >
                    {/* Color dot - centered vertically */}
                    <div
                      className="h-3 w-3 flex-shrink-0 rounded-full"
                      style={{
                        backgroundColor: calendar.backgroundColor || "#00bbff",
                      }}
                    />

                    <div className="flex-1">
                      <span className="block truncate text-sm font-medium text-zinc-300 group-hover:text-white">
                        {calendar.name}
                      </span>
                      {calendar.description && (
                        <span className="block truncate text-xs text-zinc-500 group-hover:text-zinc-400">
                          {calendar.description}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
          </div>
        </ScrollShadow>
      </div>
    );

  return null;
}
