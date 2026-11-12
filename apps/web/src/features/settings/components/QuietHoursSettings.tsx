"use client";

import { Slider, Switch } from "@heroui/react";
import { Moon02Icon } from "@icons";
import { sliderVariants } from "@/components/shared/controlVariants";
import { useQuietHours } from "@/features/settings/hooks/useQuietHours";
import {
  formatHour,
  fromAxis,
  QUIET_AXIS_END,
  QUIET_AXIS_MARKS,
  QUIET_AXIS_START,
  toAxis,
} from "@/features/settings/utils/quietHoursAxis";
import { getUserHomeTimezone } from "@/lib/timezone";
import { cn } from "@/lib/utils";

const QUIET_HOURS_DESCRIPTION =
  "During quiet hours GAIA holds anything that can wait until they end, and only interrupts you for what can't.";

const NAMED_HOURS: Record<number, string> = {
  12: "Noon",
  24: "Midnight",
  36: "Noon",
};

function markLabel(value: number): string {
  return NAMED_HOURS[value] ?? formatHour(value);
}

/** "Quiet hours": when GAIA holds what can wait, as a noon-to-noon range on the user's own clock. */
export function QuietHoursSettings() {
  const { hours, preview, save } = useQuietHours();
  if (!hours) return null;

  const span = `${formatHour(hours.start_hour)} to ${formatHour(hours.end_hour)}`;
  const length = (hours.end_hour - hours.start_hour + 24) % 24;

  return (
    <section aria-label="Quiet hours">
      <p className="mb-2 text-sm font-medium text-zinc-300">Quiet hours</p>
      <p className="mb-3 text-pretty text-sm text-zinc-500">
        {QUIET_HOURS_DESCRIPTION}
      </p>
      <div className="rounded-2xl bg-zinc-900/60 px-4 pt-3.5 pb-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-indigo-500/15">
            <Moon02Icon className="size-4 text-indigo-300" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm tabular-nums text-white">
              {hours.enabled ? span : "Off"}
            </p>
            <p className="mt-0.5 truncate text-xs text-zinc-500">
              {hours.enabled
                ? `${length} hours, in ${getUserHomeTimezone()}`
                : "GAIA reaches you at any hour"}
            </p>
          </div>
          <Switch
            size="sm"
            isSelected={hours.enabled}
            onChange={(enabled: boolean) => save({ ...hours, enabled })}
            aria-label="Use quiet hours"
          >
            <Switch.Content>
              <Switch.Control>
                <Switch.Thumb />
              </Switch.Control>
            </Switch.Content>
          </Switch>
        </div>
        <Slider
          aria-label="Quiet hours window"
          className={sliderVariants({
            size: "sm",
            color: "indigo",
            className: cn(
              "mt-4 transition-opacity duration-200",
              !hours.enabled && "pointer-events-none opacity-40",
            ),
          })}
          minValue={QUIET_AXIS_START}
          maxValue={QUIET_AXIS_END}
          step={1}
          value={toAxis(hours)}
          isDisabled={!hours.enabled}
          onChange={(value) =>
            Array.isArray(value) &&
            preview({ ...hours, ...fromAxis([value[0], value[1]]) })
          }
          onChangeEnd={(value) => {
            if (!Array.isArray(value)) return;
            const next = { ...hours, ...fromAxis([value[0], value[1]]) };
            // Thumbs that meet span no hours; the stored window stays.
            if (next.start_hour === next.end_hour) preview(null);
            else save(next);
          }}
        >
          <Slider.Track>
            <Slider.Fill />
            <Slider.Thumb index={0} />
            <Slider.Thumb index={1} />
          </Slider.Track>
          <Slider.Marks className="pointer-events-none">
            {QUIET_AXIS_MARKS.map((value) => (
              <Slider.Mark
                key={value}
                value={value}
                className={toneVariants({
                  tone: "faint",
                  className: "whitespace-nowrap text-[11px] tabular-nums",
                })}
              >
                {markLabel(value)}
              </Slider.Mark>
            ))}
          </Slider.Marks>
        </Slider>
      </div>
    </section>
  );
}
