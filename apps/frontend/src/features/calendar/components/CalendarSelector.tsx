import { Chip } from "@heroui/chip";

import { isTooDark } from "@/features/calendar/utils/calendarUtils";
import { ViewIcon, ViewOffSlashIcon } from "@/icons";
import type {
  CalendarChipProps,
  CalendarSelectorProps,
} from "@/types/features/calendarTypes";

function CalendarChip({ calendar, selected, onSelect }: CalendarChipProps) {
  const baseColor = calendar.backgroundColor || "#6366f1";
  const computedColor = isTooDark(baseColor) ? "#ffffff" : baseColor;
  // const contrastingTextColor = getContrastingColor(computedColor);

  return (
    <div
      className={`relative min-w-full cursor-pointer rounded-lg px-2 text-left transition hover:bg-zinc-800`}
      onClick={() => onSelect(calendar.id)}
    >
      <Chip
        className={`${selected ? "text-zinc-300" : "text-zinc-600"} `}
        variant="faded"
        startContent={
          <div
            className="mr-2 aspect-square min-h-[12px] min-w-[12px] rounded-full"
            style={{
              backgroundColor: computedColor,
            }}
          />
        }
        endContent={
          selected ? (
            <ViewIcon className="mr-1" width={17} height={17} />
          ) : (
            <ViewOffSlashIcon className="mr-1" width={17} height={17} />
          )
        }
        style={{
          margin: "0",
          background: "transparent",
          borderWidth: "0px",
          // color: computedColor,
          borderRadius: "7px",
        }}
      >
        <div className="text-sm truncate max-w-[calc(var(--sidebar-width)-90px)] w-[calc(var(--sidebar-width)-90px)]">
          {calendar.summary}
        </div>
      </Chip>
    </div>
  );
}

export default function CalendarSelector({
  calendars,
  selectedCalendars,
  onCalendarSelect,
}: CalendarSelectorProps) {
  return (
    <div
      className={`relative flex flex-col justify-center gap-1 transition-all`}
    >
      {calendars && calendars.length > 0 ? (
        [...calendars]
          .sort((a, b) => a.summary.localeCompare(b.summary))
          .map((calendar) => (
            <CalendarChip
              key={calendar.id}
              calendar={calendar}
              selected={selectedCalendars.includes(calendar.id)}
              onSelect={onCalendarSelect}
            />
          ))
      ) : (
        <div className="p-3 text-sm text-foreground-500">
          You have no Calendars
        </div>
      )}
    </div>
  );
}
