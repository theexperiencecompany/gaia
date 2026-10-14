import type { CalendarListFetchData } from "@/types/features/calendarTypes";

interface CalendarListFetchSectionProps {
  calendars: CalendarListFetchData[];
}

/**
 * Read-only render of a legacy calendar-list fetch restored from history.
 * The interactive draft/add flows moved to HIL approvals; this only replays
 * what an older conversation already showed, so it carries no select action.
 */
export function CalendarListFetchSection({
  calendars,
}: CalendarListFetchSectionProps) {
  const items = calendars.filter((calendar) => calendar.name);
  return (
    <div className="w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
      <div className="text-xs font-medium text-zinc-400">Calendars</div>
      {items.length === 0 ? (
        <div className="mt-2 text-xs text-zinc-500">
          No calendars in this list.
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          {items.map((calendar) => (
            <div
              key={calendar.id || calendar.name}
              className="flex items-start gap-2 rounded-2xl bg-zinc-900 p-3"
            >
              <div
                aria-hidden
                className="mt-1 size-2 shrink-0 rounded-full"
                style={{
                  backgroundColor: calendar.backgroundColor || "#00bbff",
                }}
              />
              <div className="min-w-0">
                <div className="text-sm leading-tight text-zinc-100">
                  {calendar.name}
                </div>
                {calendar.description && (
                  <div className="mt-0.5 text-xs text-zinc-500">
                    {calendar.description}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
