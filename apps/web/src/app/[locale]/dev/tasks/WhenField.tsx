"use client";

import { Button } from "@heroui/button";
import { Divider } from "@heroui/divider";
import { Input, Textarea } from "@heroui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Calendar, TimeInput } from "@heroui/react";
import { FilterHorizontalIcon, Search01Icon, Tick02Icon } from "@icons";
import { getLocalTimeZone, parseDate, Time } from "@internationalized/date";
import { type ReactNode, useMemo, useState } from "react";

import { TimezoneAutocomplete } from "@/features/workflows/components/TimezoneAutocomplete";
import { describeCron } from "@/features/workflows/utils/cronUtils";
import { getUserHomeTimezone } from "@/lib/timezone";
import { cn } from "@/lib/utils";
import { getTimezoneList, normalizeTimezone } from "@/utils/timezoneUtils";
import { APP_NAMES, DEMO_TRIGGERS } from "./demoTriggers";
import { AppIcon, PropertyRow, WHEN_ICONS } from "./TaskParts";
import type { TaskWhen } from "./taskModel";
import {
  DEFAULT_REPEAT,
  fromCron,
  inDays,
  NO_WHEN,
  onDate,
  onEvent,
  onSchedule,
  type Repeat,
  toCron,
} from "./whenModel";

type Mode = "date" | "repeat" | "event";
type Change = (when: TaskWhen) => void;

const MODES: { key: Mode; label: string; kind: TaskWhen["kind"] }[] = [
  { key: "date", label: "Date", kind: "at" },
  { key: "repeat", label: "Repeat", kind: "schedule" },
  { key: "event", label: "Event", kind: "event" },
];

/** Every control in the editor: 36px tall, 12px corners, one step darker than the popover. */
const QUIET_FIELD =
  "h-9 min-h-9 rounded-xl bg-zinc-900 shadow-none data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900 group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0";

const TEXT_BUTTON =
  "h-7 min-w-0 justify-start px-1 text-[13px] font-normal text-zinc-500 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-200";

/** When a task is due or runs, on one line. The detail is one click away. */
export function WhenValue({ when }: { when: TaskWhen }) {
  if (!when.label) return <span className="text-zinc-500">No date</span>;
  const Icon = WHEN_ICONS[when.kind];
  return (
    <span
      className={cn(
        "flex min-w-0 items-center gap-1.5",
        when.overdue
          ? "text-red-400"
          : when.isToday
            ? "text-emerald-400"
            : "text-zinc-200",
      )}
    >
      {when.app ? (
        <AppIcon id={when.app} size={15} />
      ) : (
        <Icon className="size-4 shrink-0 opacity-70" />
      )}
      <span className="truncate">
        {when.overdue ? `Overdue, ${when.label}` : when.label}
      </span>
      {when.condition && (
        <FilterHorizontalIcon
          aria-label="Filtered"
          className="size-3.5 shrink-0 text-zinc-500"
        />
      )}
    </span>
  );
}

/** One choice among a few: the neutral pill every picker in here uses. */
function Pick({
  isSelected,
  onPress,
  label,
  className,
  children,
}: {
  isSelected: boolean;
  onPress: () => void;
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Button
      size="sm"
      variant="light"
      disableRipple
      aria-label={label}
      aria-pressed={isSelected}
      onPress={onPress}
      className={cn(
        "h-8 min-w-0 px-0 text-[13px]",
        isSelected
          ? "bg-primary font-medium text-black data-[hover=true]:bg-primary"
          : "text-zinc-300 data-[hover=true]:bg-zinc-700",
        className,
      )}
    >
      {children}
    </Button>
  );
}

/** A choice of one: a 36px track with the chosen segment raised inside it. */
function Segmented<Key extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: Key; label: string; icon?: ReactNode }[];
  value: Key;
  onChange: (key: Key) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="flex h-9 gap-1 rounded-xl bg-zinc-900 p-1"
    >
      {options.map((option) => {
        const isOn = option.key === value;
        return (
          <Button
            key={option.key}
            size="sm"
            variant="light"
            disableRipple
            role="radio"
            aria-checked={isOn}
            onPress={() => onChange(option.key)}
            startContent={option.icon}
            className={cn(
              "h-7 min-w-0 flex-1 gap-1.5 rounded-lg text-[13px] font-medium",
              isOn
                ? "bg-zinc-700 text-zinc-100 data-[hover=true]:bg-zinc-700"
                : "text-zinc-400 data-[hover=true]:bg-transparent data-[hover=true]:text-zinc-200",
            )}
          >
            {option.label}
          </Button>
        );
      })}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex h-9 items-center justify-between gap-3">
      <span className="px-1 text-[13px] text-zinc-500">{label}</span>
      {children}
    </div>
  );
}

function TimeField({
  hour,
  minute,
  onChange,
}: {
  hour: number;
  minute: number;
  onChange: (hour: number, minute: number) => void;
}) {
  return (
    <TimeInput
      aria-label="Time"
      size="sm"
      hourCycle={12}
      value={new Time(hour, minute)}
      onChange={(time) => time && onChange(time.hour, time.minute)}
      classNames={{
        base: "w-auto",
        inputWrapper: cn(QUIET_FIELD, "px-3"),
        input: "text-sm",
      }}
    />
  );
}

const QUICK_DATES = [
  { label: "Today", days: 0 },
  { label: "Tomorrow", days: 1 },
  { label: "Next week", days: 7 },
];

function DatePane({ when, onChange }: { when: TaskWhen; onChange: Change }) {
  const date = when.kind === "at" ? when.date : undefined;
  const time = date ? when.time : undefined;
  const [hour, minute] = (time ?? "9:00").split(":").map(Number);

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-1.5">
        {QUICK_DATES.map((quick) => {
          const target = inDays(quick.days, time);
          return (
            <Button
              key={quick.label}
              size="sm"
              variant="light"
              disableRipple
              onPress={() => onChange(target)}
              className="h-9 min-w-0 rounded-xl bg-zinc-900 px-0 text-[13px] text-zinc-300 data-[hover=true]:bg-zinc-700"
            >
              {quick.label}
            </Button>
          );
        })}
      </div>
      <Calendar
        aria-label="Date"
        showShadow={false}
        calendarWidth={280}
        value={date ? parseDate(date) : null}
        onChange={(day) =>
          onChange(onDate(day.toDate(getLocalTimeZone()), time))
        }
        classNames={{
          base: "w-full border-none !bg-transparent shadow-none",
          headerWrapper: "!bg-transparent px-1 pb-2 pt-1",
          gridHeader: "!bg-transparent shadow-none",
          gridHeaderCell: "text-xs font-normal text-zinc-500",
          gridWrapper: "pb-1",
          title: "text-sm font-medium text-zinc-200",
          cellButton:
            "text-[13px] data-[selected=true]:bg-primary data-[selected=true]:font-medium data-[selected=true]:text-black data-[selected=true]:data-[hover=true]:bg-primary data-[today=true]:text-primary data-[selected=true]:data-[today=true]:text-black data-[hover=true]:bg-zinc-700",
        }}
      />
      {date && (
        <Field label="Time">
          {time ? (
            <div className="flex items-center gap-2">
              <TimeField
                hour={hour}
                minute={minute}
                onChange={(h, m) =>
                  onChange(
                    onDate(
                      parseDate(date).toDate(getLocalTimeZone()),
                      `${h}:${String(m).padStart(2, "0")}`,
                    ),
                  )
                }
              />
              <Button
                size="sm"
                variant="light"
                className={TEXT_BUTTON}
                onPress={() =>
                  onChange(onDate(parseDate(date).toDate(getLocalTimeZone())))
                }
              >
                Remove
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="light"
              className={TEXT_BUTTON}
              onPress={() =>
                onChange(
                  onDate(parseDate(date).toDate(getLocalTimeZone()), "9:00"),
                )
              }
            >
              Add a time
            </Button>
          )}
        </Field>
      )}
    </div>
  );
}

const EVERY: { key: Repeat["every"]; label: string }[] = [
  { key: "day", label: "Daily" },
  { key: "week", label: "Weekly" },
  { key: "month", label: "Monthly" },
];

/** Monday first, by the cron day number each stands for. */
const WEEK = [
  { day: 1, letter: "M", name: "Monday" },
  { day: 2, letter: "T", name: "Tuesday" },
  { day: 3, letter: "W", name: "Wednesday" },
  { day: 4, letter: "T", name: "Thursday" },
  { day: 5, letter: "F", name: "Friday" },
  { day: 6, letter: "S", name: "Saturday" },
  { day: 0, letter: "S", name: "Sunday" },
];

const MONTH_DAYS = Array.from({ length: 31 }, (_, index) => index + 1);
/** The last day every month has; a later one is skipped in shorter months. */
const LAST_COMMON_DAY = 28;

function TimezoneField({
  timezone,
  onChange,
}: {
  timezone: string;
  onChange: (timezone: string) => void;
}) {
  const current = normalizeTimezone(timezone);
  const options = useMemo(() => {
    const all = getTimezoneList(true).map(({ value, label, offset }) => ({
      value,
      label,
      offset,
    }));
    return all.some((zone) => zone.value === current)
      ? all
      : [{ value: current, label: current, offset: "" }, ...all];
  }, [current]);
  return (
    <TimezoneAutocomplete
      timezone={current}
      options={options}
      onChange={onChange}
      className="w-44 [&_[data-slot=input-wrapper]]:!h-9 [&_[data-slot=input-wrapper]]:!rounded-xl [&_[data-slot=input-wrapper]]:!bg-zinc-900 [&_[data-slot=input-wrapper]]:shadow-none"
    />
  );
}

function RepeatPane({
  when,
  onChange,
  forGaia,
}: {
  when: TaskWhen;
  onChange: Change;
  forGaia: boolean;
}) {
  const cron = when.cron ?? "";
  const timezone = when.timezone ?? getUserHomeTimezone();
  const parsed = fromCron(cron);
  const [isCustom, setIsCustom] = useState(parsed === null);
  const repeat = parsed ?? DEFAULT_REPEAT;
  const set = (patch: Partial<Repeat>) =>
    onChange(onSchedule(toCron({ ...repeat, ...patch }), timezone));
  const zone = forGaia && (
    <Field label="Timezone">
      <TimezoneField
        timezone={timezone}
        onChange={(next) => onChange(onSchedule(cron, next))}
      />
    </Field>
  );

  if (isCustom) {
    return (
      <div className="space-y-1">
        <Input
          aria-label="Cron expression"
          size="sm"
          value={cron}
          onValueChange={(next) => onChange(onSchedule(next, timezone))}
          placeholder="0 9 * * 1-5"
          classNames={{
            inputWrapper: QUIET_FIELD,
            input: "font-mono text-sm",
          }}
        />
        <p className="px-0.5 pt-1 text-xs text-zinc-500">
          {describeCron(cron) ?? "minute, hour, day, month, weekday"}
        </p>
        {zone}
        <Button
          size="sm"
          variant="light"
          className={TEXT_BUTTON}
          onPress={() => {
            setIsCustom(false);
            if (!parsed) onChange(onSchedule(toCron(DEFAULT_REPEAT), timezone));
          }}
        >
          Pick days and a time instead
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Segmented
        label="How often"
        options={EVERY}
        value={repeat.every}
        onChange={(every) => set({ every })}
      />

      {repeat.every === "week" && (
        <div className="grid grid-cols-7 justify-items-center py-1">
          {WEEK.map(({ day, letter, name }) => {
            const isOn = repeat.days.includes(day);
            return (
              <Pick
                key={day}
                label={name}
                isSelected={isOn}
                onPress={() => {
                  const days = isOn
                    ? repeat.days.filter((other) => other !== day)
                    : [...repeat.days, day];
                  if (days.length > 0) set({ days });
                }}
                className={cn("size-8 rounded-full", !isOn && "bg-zinc-900")}
              >
                {letter}
              </Pick>
            );
          })}
        </div>
      )}

      {repeat.every === "month" && (
        <div className="py-1">
          <div className="grid grid-cols-7 justify-items-center gap-y-0.5">
            {MONTH_DAYS.map((day) => (
              <Pick
                key={day}
                label={`Day ${day}`}
                isSelected={repeat.dayOfMonth === day}
                onPress={() => set({ dayOfMonth: day })}
                className="size-8 rounded-full tabular-nums"
              >
                {day}
              </Pick>
            ))}
          </div>
          {repeat.dayOfMonth > LAST_COMMON_DAY && (
            <p className="px-0.5 pt-2 text-xs text-zinc-500">
              Months without a day {repeat.dayOfMonth} are skipped.
            </p>
          )}
        </div>
      )}

      <div className="space-y-2">
        <Field label="Time">
          <TimeField
            hour={repeat.hour}
            minute={repeat.minute}
            onChange={(hour, minute) => set({ hour, minute })}
          />
        </Field>
        {zone}
      </div>
      {forGaia && (
        <Button
          size="sm"
          variant="light"
          className={TEXT_BUTTON}
          onPress={() => setIsCustom(true)}
        >
          Use a cron expression
        </Button>
      )}
    </div>
  );
}

function EventPane({ when, onChange }: { when: TaskWhen; onChange: Change }) {
  const selected = DEMO_TRIGGERS.find((item) => item.slug === when.trigger);
  const [isChoosing, setIsChoosing] = useState(!selected);
  const [query, setQuery] = useState("");

  if (selected && !isChoosing) {
    return (
      <div className="space-y-3">
        <Button
          variant="light"
          disableRipple
          aria-label="Change the event"
          onPress={() => setIsChoosing(true)}
          className="h-9 w-full justify-start gap-2 rounded-xl bg-zinc-900 px-3 text-sm font-normal text-zinc-100 data-[hover=true]:bg-zinc-900/60"
        >
          <AppIcon id={selected.app} size={16} />
          <span className="truncate">{selected.name}</span>
          <span className="ml-auto text-[13px] text-zinc-500">Change</span>
        </Button>
        <div>
          <p className="px-1 pb-1.5 text-[13px] text-zinc-500">Only when</p>
          <Textarea
            aria-label="Only when"
            value={when.condition ?? ""}
            onValueChange={(condition) =>
              onChange(onEvent(selected.slug, condition))
            }
            placeholder="It has an invoice attached"
            minRows={2}
            variant="flat"
            classNames={{
              inputWrapper: cn(QUIET_FIELD, "h-auto px-3 py-2"),
              input: "text-sm leading-5 placeholder:text-zinc-600",
            }}
          />
          <p className="px-1 pt-1.5 text-xs text-zinc-500">
            Optional. GAIA skips everything else.
          </p>
        </div>
      </div>
    );
  }

  const needle = query.trim().toLowerCase();
  const matches = DEMO_TRIGGERS.filter((item) =>
    `${APP_NAMES[item.app]} ${item.name}`.toLowerCase().includes(needle),
  );
  const apps = [...new Set(matches.map((item) => item.app))];

  return (
    <div className="space-y-1">
      <Input
        autoFocus
        aria-label="Search events"
        size="sm"
        value={query}
        onValueChange={setQuery}
        placeholder="Search apps and events"
        startContent={
          <Search01Icon className="size-4 shrink-0 text-zinc-500" />
        }
        classNames={{ inputWrapper: QUIET_FIELD }}
      />
      <div className="-mx-1 max-h-72 overflow-y-auto px-1">
        {apps.map((app) => (
          <section key={app}>
            <h4 className="px-3 pb-1 pt-3 text-xs text-zinc-500">
              {APP_NAMES[app]}
            </h4>
            {matches
              .filter((item) => item.app === app)
              .map((item) => (
                <Button
                  key={item.slug}
                  size="sm"
                  variant="light"
                  onPress={() => {
                    onChange(onEvent(item.slug, when.condition));
                    setIsChoosing(false);
                    setQuery("");
                  }}
                  className="h-9 w-full justify-start gap-2 rounded-xl px-3 text-sm font-normal text-zinc-200 data-[hover=true]:bg-zinc-700"
                >
                  <AppIcon id={item.app} size={15} />
                  {item.name}
                  {item.slug === when.trigger && (
                    <Tick02Icon className="ml-auto size-4 text-zinc-400" />
                  )}
                </Button>
              ))}
          </section>
        ))}
        {matches.length === 0 && (
          <p className="px-2 py-6 text-center text-[13px] text-zinc-500">
            Nothing matches
          </p>
        )}
      </div>
    </div>
  );
}

function WhenEditor({
  when,
  onChange,
  forGaia,
  onClear,
}: {
  when: TaskWhen;
  onChange: Change;
  forGaia: boolean;
  onClear: () => void;
}) {
  const modes = MODES.filter((mode) => forGaia || mode.key !== "event");
  const [mode, setMode] = useState<Mode>(
    () => MODES.find((item) => item.kind === when.kind)?.key ?? "date",
  );

  // What each mode held before you switched away, so looking at another one loses nothing.
  const [kept, setKept] = useState<Partial<Record<Mode, TaskWhen>>>({});

  const choose = (next: Mode) => {
    if (next === mode) return;
    const current = MODES.find((item) => item.kind === when.kind)?.key;
    if (current) setKept({ ...kept, [current]: when });
    setMode(next);
    const before = kept[next];
    if (before) onChange(before);
    // Repeating has a sensible default, so choosing it sets it; a date and an event are picked.
    else if (next === "repeat" && when.kind !== "schedule") {
      onChange(onSchedule(toCron(DEFAULT_REPEAT), getUserHomeTimezone()));
    }
  };

  return (
    <div className="w-full space-y-3">
      <Segmented
        label="When"
        options={modes.map((item) => {
          const Icon = WHEN_ICONS[item.kind];
          return {
            key: item.key,
            label: item.label,
            icon: <Icon className="size-3.5" />,
          };
        })}
        value={mode}
        onChange={choose}
      />

      {mode === "date" && <DatePane when={when} onChange={onChange} />}
      {mode === "repeat" && when.kind === "schedule" && (
        <RepeatPane when={when} onChange={onChange} forGaia={forGaia} />
      )}
      {mode === "event" && <EventPane when={when} onChange={onChange} />}

      {when.kind !== "anytime" && (
        <>
          <Divider className="bg-zinc-700/60" />
          <Button
            size="sm"
            variant="light"
            onPress={onClear}
            className="h-9 w-full justify-start rounded-xl px-3 text-sm font-normal text-zinc-400 data-[hover=true]:bg-zinc-700 data-[hover=true]:text-zinc-200"
          >
            {forGaia ? "Only when I ask" : "No date"}
          </Button>
        </>
      )}
    </div>
  );
}

/**
 * The one "when" every task has: nothing, a date, a repeat, or (for GAIA) an app
 * event. The row shows it in a line; the editor opens under it, inside the sidebar.
 */
export default function WhenField({
  when,
  onChange,
  forGaia,
}: {
  when: TaskWhen;
  onChange: Change;
  forGaia: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <PropertyRow label="When">
      <Popover
        isOpen={isOpen}
        onOpenChange={setIsOpen}
        placement="bottom-end"
        offset={6}
        triggerScaleOnOpen={false}
      >
        <PopoverTrigger>
          <Button
            size="sm"
            variant="light"
            aria-label="When"
            disableAnimation
            className={cn(
              "-ml-2 h-8 min-w-0 flex-1 justify-start px-2 text-sm font-normal data-[hover=true]:bg-zinc-800",
              isOpen && "bg-zinc-800",
            )}
          >
            <WhenValue when={when} />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[19rem] rounded-2xl border-none bg-zinc-800 p-3 shadow-xl">
          <WhenEditor
            when={when}
            onChange={onChange}
            forGaia={forGaia}
            onClear={() => {
              onChange(NO_WHEN);
              setIsOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
    </PropertyRow>
  );
}
