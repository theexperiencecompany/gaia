import { ScrollShadow } from "@heroui/scroll-shadow";

import { GoogleCalendarIcon } from "@/components";
import type { CalendarListFetchData } from "@/types/features/calendarTypes";

interface CalendarListFetchProps {
  calendars?: CalendarListFetchData[] | null;
}

export default function CalendarListFetchCard({
  calendars,
}: CalendarListFetchProps) {
  if (!!calendars && calendars.length > 0)
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

        <ScrollShadow className="max-h-[200px] divide-y divide-gray-700 overflow-x-hidden">
          {calendars.length > 0 &&
            calendars
              .slice() // Slice to copy the array because of immutability
              .sort((a, b) => a.name.localeCompare(b.name)) // Sort alphebetically
              .map((calendar, index) => (
                <div
                  key={index}
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
                    <span className="block truncate text-sm font-medium text-gray-300 group-hover:text-white">
                      {calendar.name}
                    </span>
                    {calendar.description && (
                      <span className="block truncate text-xs text-gray-500 group-hover:text-gray-400">
                        {calendar.description}
                      </span>
                    )}
                  </div>
                </div>
              ))}
        </ScrollShadow>
      </div>
    );
}
