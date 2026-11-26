import { Separator } from "@heroui/react";
import { formatDay } from "@shared/utils";

/** The day a run of chat rows happened on, centred on a rule between it and the day before. */
export function DayDivider({ at }: Readonly<{ at: Date }>) {
  return (
    <div className="flex items-center gap-3 px-1 pt-6 pb-4 select-none">
      <Separator className="min-w-0 flex-1" />
      <time
        dateTime={at.toISOString()}
        className="shrink-0 text-xs font-medium text-zinc-500"
        suppressHydrationWarning
      >
        {formatDay(at, "fullDay")}
      </time>
      <Separator className="min-w-0 flex-1" />
    </div>
  );
}
