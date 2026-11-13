import { Chip } from "@heroui/react";
import { ViewIcon, ViewOffSlashIcon } from "@icons";
import { toneVariants } from "@/components/shared/tone";
import { isTooDark } from "@/features/calendar/utils/calendarUtils";
import type {
  CalendarChipProps,
  CalendarSelectorProps,
} from "@/types/features/calendarTypes";

function CalendarChip({ calendar, selected, onSelect }: CalendarChipProps) {
  const baseColor = calendar.backgroundColor || "#6366f1";
  const computedColor = isTooDark(baseColor) ? "#ffffff" : baseColor;
  // const contrastingTextColor = getContrastingColor(computedColor);

  return (
    <button
      type="button"
      className="relative min-w-full cursor-pointer rounded-lg px-2 text-left transition hover:bg-zinc-800"
      aria-label={`Toggle calendar ${calendar.summary}`}
      onClick={() => onSelect(calendar.id)}
    >
      <Chip
        className={toneVariants({ tone: selected ? "dim" : "faint" })}
        variant="tertiary"
      >
        <div
          className="mr-2 aspect-square min-h-[12px] min-w-[12px] rounded-full"
          style={{
            backgroundColor: computedColor,
          }}
        />
        <Chip.Label>
          <div className="text-sm truncate max-w-[calc(var(--sidebar-width)-90px)] w-[calc(var(--sidebar-width)-90px)]">
            {calendar.summary}
          </div>
        </Chip.Label>
        {selected ? (
          <ViewIcon className="mr-1" width={17} height={17} />
        ) : (
          <ViewOffSlashIcon className="mr-1" width={17} height={17} />
        )}
      </Chip>
    </button>
  );
}

export default function CalendarSelector({
  calendars,
  selectedCalendars,
  onCalendarSelect,
}: CalendarSelectorProps) {
  const selectedCalendarSet = new Set(selectedCalendars);

  return (
    <div className={`relative flex flex-col justify-center gap-1`}>
      {calendars && calendars.length > 0 ? (
        calendars
          .toSorted((a, b) => a.summary.localeCompare(b.summary))
          .map((calendar) => (
            <CalendarChip
              key={calendar.id}
              calendar={calendar}
              selected={selectedCalendarSet.has(calendar.id)}
              onSelect={onCalendarSelect}
            />
          ))
      ) : (
        <div className="p-3 text-sm text-zinc-400">
          You have no Calendars
        </div>
      )}
    </div>
  );
}
