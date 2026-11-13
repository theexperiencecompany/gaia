"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Slider } from "@heroui/slider";
import { Add01Icon, Cancel01Icon, Notification01Icon } from "@icons";
import { useAttentionSettings } from "@/features/settings/hooks/useAttentionSettings";
import {
  ATTENTION_BUDGET_MARKS,
  ATTENTION_BUDGET_MAX,
  ATTENTION_CHECKIN_MAX,
  NEW_CHECKIN_TIME,
  toTimeInput,
} from "@/features/settings/utils/attention";

const DESCRIPTION =
  "GAIA tells you what you asked for right away. Anything else it holds for a check-in once this many have gone out today.";

/** "Updates": how many things GAIA tells the user unprompted a day, and when it checks in. */
export function UpdatesSettings() {
  const { settings, preview, save } = useAttentionSettings();
  if (!settings) return null;

  const budget = settings.max_unsolicited_per_day ?? 0;
  const checkins = settings.checkin_times ?? [];

  const saveCheckins = (times: string[]) =>
    save({ ...settings, checkin_times: times });

  return (
    <section aria-label="Updates">
      <p className="mb-2 text-sm font-medium text-zinc-300">Updates</p>
      <p className="mb-3 text-pretty text-sm text-zinc-500">{DESCRIPTION}</p>
      <div className="rounded-2xl bg-zinc-900/60 px-4 pt-3.5 pb-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-indigo-500/15">
            <Notification01Icon className="size-4 text-indigo-300" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm tabular-nums text-white">
              {budget === 0 ? "Only at check-ins" : `${budget} a day`}
            </p>
            <p className="mt-0.5 truncate text-xs text-zinc-500">
              Updates GAIA sends without being asked
            </p>
          </div>
        </div>
        <Slider
          aria-label="Updates per day"
          className="mt-4"
          minValue={0}
          maxValue={ATTENTION_BUDGET_MAX}
          step={1}
          size="sm"
          value={budget}
          onChange={(value) =>
            typeof value === "number" &&
            preview({ ...settings, max_unsolicited_per_day: value })
          }
          onChangeEnd={(value) =>
            typeof value === "number" &&
            save({ ...settings, max_unsolicited_per_day: value })
          }
          marks={ATTENTION_BUDGET_MARKS.map((value) => ({
            value,
            label: String(value),
          }))}
          classNames={{
            filler: "bg-indigo-400/70",
            thumb: "bg-indigo-300 after:bg-indigo-300",
            mark: "pointer-events-none text-[11px] text-zinc-500 tabular-nums",
          }}
        />
        <p className="mt-8 mb-2 text-xs text-zinc-500">
          Check-ins, besides the one when quiet hours end
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {checkins.map((time) => (
            <Input
              key={time}
              aria-label={`Check-in at ${toTimeInput(time)}`}
              type="time"
              size="sm"
              className="w-32"
              value={toTimeInput(time)}
              onValueChange={(next) =>
                next &&
                saveCheckins(checkins.map((t) => (t === time ? next : t)))
              }
              endContent={
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  radius="full"
                  aria-label={`Remove the check-in at ${toTimeInput(time)}`}
                  onPress={() =>
                    saveCheckins(checkins.filter((t) => t !== time))
                  }
                >
                  <Cancel01Icon className="size-3.5" />
                </Button>
              }
            />
          ))}
          {checkins.length < ATTENTION_CHECKIN_MAX && (
            <Button
              size="sm"
              variant="flat"
              radius="full"
              startContent={<Add01Icon className="size-3.5" />}
              isDisabled={checkins.some(
                (time) => toTimeInput(time) === NEW_CHECKIN_TIME,
              )}
              onPress={() => saveCheckins([...checkins, NEW_CHECKIN_TIME])}
            >
              Add check-in
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
