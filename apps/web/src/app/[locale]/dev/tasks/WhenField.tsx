"use client";

import { Calendar, Input, Popover, Separator, TimeField } from "@heroui/react";
import { FilterHorizontalIcon, WebhookIcon } from "@icons";
import { getLocalTimeZone, parseDate, Time } from "@internationalized/date";
import { useLocale } from "next-intl";
import { type ReactNode, useMemo, useState } from "react";
import { I18nProvider } from "react-aria-components";

import { calendarVariants } from "@/components/shared/calendarVariants";
import {
  inputVariants,
  overlayVariants,
  separatorVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { toneVariants } from "@/components/shared/tone";
import { TimezoneAutocomplete } from "@/features/workflows/components/TimezoneAutocomplete";
import { describeCron } from "@/features/workflows/utils/cronUtils";
import { getUserHomeTimezone } from "@/lib/timezone";
import { cn } from "@/lib/utils";
import { getTimezoneList, normalizeTimezone } from "@/utils/timezoneUtils";
import { AppIcon } from "./AppIcon";
import EventPane from "./EventPane";
import { PropertyRow } from "./PropertyRow";
import Segmented from "./Segmented";
import { WHEN_ICONS } from "./taskIcons";
import { isRepeating, type TaskWhen, type WhenKind } from "./taskModel";
import { WatchIcon } from "./WatchIcon";
import WhenEnds from "./WhenEnds";
import { EDITOR_FIELD, Field, TextAction } from "./WhenParts";
import { watchEndsLabel } from "./watchModel";
import {
  DEFAULT_REPEAT,
  endsLabel,
  fromCron,
  inDays,
  NO_WHEN,
  onDate,
  onSchedule,
  type Repeat,
  toCron,
} from "./whenModel";

type Mode = "date" | "repeat" | "event";
type Change = (when: TaskWhen) => void;

const MODES: { key: Mode; label: string; kinds: WhenKind[] }[] = [
  { key: "date", label: "Date", kinds: ["at"] },
  { key: "repeat", label: "Repeat", kinds: ["schedule"] },
  // A watch and a webhook are things that happen too, so they are chosen with the app events.
  { key: "event", label: "Event", kinds: ["event", "watch"] },
];

const modeOf = (when: TaskWhen) =>
  MODES.find((item) => item.kinds.includes(when.kind))?.key;

const calendar = calendarVariants();

/** When a task is due or runs, on one line. The detail is one click away. */
function WhenValue({ when }: { when: TaskWhen }) {
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
      {when.watch ? (
        <WatchIcon source={when.watch.source} size={15} />
      ) : when.app ? (
        <AppIcon id={when.app} size={15} />
      ) : when.webhook ? (
        <WebhookIcon className="size-4 shrink-0 opacity-70" />
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

/** One day among a few: a 32px circle, on the accent while chosen. */
function DayPick({
  isSelected,
  onPress,
  label,
  isSunken = false,
  children,
}: {
  isSelected: boolean;
  onPress: () => void;
  label: string;
  /** Sits in its own well when off, as a weekday does. */
  isSunken?: boolean;
  children: ReactNode;
}) {
  return (
    <GaiaButton
      size="sm"
      variant={isSelected ? "primary" : isSunken ? "sunken" : "raised-ghost"}
      tone={isSelected ? "default" : "dim"}
      shape="pill"
      inset="none"
      isIconOnly
      aria-label={label}
      aria-pressed={isSelected}
      onPress={onPress}
      className={cn(
        "size-8 min-w-0 text-[13px] tabular-nums",
        isSelected && "font-medium",
      )}
    >
      {children}
    </GaiaButton>
  );
}

function ClockField({
  hour,
  minute,
  onChange,
}: {
  hour: number;
  minute: number;
  onChange: (hour: number, minute: number) => void;
}) {
  return (
    <TimeField
      aria-label="Time"
      hourCycle={12}
      shouldForceLeadingZeros
      value={new Time(hour, minute)}
      onChange={(time) => time && onChange(time.hour, time.minute)}
      className="w-auto"
    >
      <TimeField.Group className={EDITOR_FIELD}>
        <TimeField.Input>
          {(segment) => <TimeField.Segment segment={segment} />}
        </TimeField.Input>
      </TimeField.Group>
    </TimeField>
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
        {QUICK_DATES.map((quick) => (
          <GaiaButton
            key={quick.label}
            size="sm"
            variant="sunken"
            shape="md"
            tone="dim"
            inset="none"
            onPress={() => onChange(inDays(quick.days, time))}
            className="h-9 min-w-0 text-[13px]"
          >
            {quick.label}
          </GaiaButton>
        ))}
      </div>
      <Calendar
        aria-label="Date"
        value={date ? parseDate(date) : null}
        onChange={(day) =>
          onChange(onDate(day.toDate(getLocalTimeZone()), time))
        }
        className={calendar.base()}
      >
        <Calendar.Header className={calendar.header()}>
          <Calendar.NavButton
            slot="previous"
            className={calendar.navButton()}
          />
          <Calendar.Heading className={calendar.heading()} />
          <Calendar.NavButton slot="next" className={calendar.navButton()} />
        </Calendar.Header>
        <Calendar.Grid weekdayStyle="narrow" className={calendar.grid()}>
          <Calendar.GridHeader>
            {(day) => (
              <Calendar.HeaderCell className={calendar.headerCell()}>
                {day}
              </Calendar.HeaderCell>
            )}
          </Calendar.GridHeader>
          <Calendar.GridBody>
            {(day) => <Calendar.Cell date={day} className={calendar.cell()} />}
          </Calendar.GridBody>
        </Calendar.Grid>
      </Calendar>
      {date && (
        <Field label="Time">
          {time ? (
            <div className="flex items-center gap-2">
              <ClockField
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
              <TextAction
                onPress={() =>
                  onChange(onDate(parseDate(date).toDate(getLocalTimeZone())))
                }
              >
                Remove
              </TextAction>
            </div>
          ) : (
            <TextAction
              onPress={() =>
                onChange(
                  onDate(parseDate(date).toDate(getLocalTimeZone()), "9:00"),
                )
              }
            >
              Add a time
            </TextAction>
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
      className={inputVariants({ variant: "sunken", className: "w-44" })}
    />
  );
}

function RepeatPane({
  when,
  onChange,
  forGaia,
  limit,
}: {
  when: TaskWhen;
  onChange: Change;
  forGaia: boolean;
  /** When it stops on its own, with the other settings of the repeat. */
  limit?: ReactNode;
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
          value={cron}
          onChange={(event) =>
            onChange(onSchedule(event.target.value, timezone))
          }
          placeholder="0 9 * * 1-5"
          className={inputVariants({
            variant: "sunken",
            className: toneVariants({
              tone: "white",
              className: "w-full font-mono text-sm",
            }),
          })}
        />
        <p className="px-0.5 pt-1 text-xs text-zinc-500">
          {describeCron(cron) ?? "minute, hour, day, month, weekday"}
        </p>
        {zone}
        {limit}
        <TextAction
          onPress={() => {
            setIsCustom(false);
            if (!parsed) onChange(onSchedule(toCron(DEFAULT_REPEAT), timezone));
          }}
        >
          Pick days and a time instead
        </TextAction>
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
              <DayPick
                key={day}
                label={name}
                isSelected={isOn}
                isSunken
                onPress={() => {
                  const days = isOn
                    ? repeat.days.filter((other) => other !== day)
                    : [...repeat.days, day];
                  if (days.length > 0) set({ days });
                }}
              >
                {letter}
              </DayPick>
            );
          })}
        </div>
      )}

      {repeat.every === "month" && (
        <div className="py-1">
          <div className="grid grid-cols-7 justify-items-center gap-y-0.5">
            {MONTH_DAYS.map((day) => (
              <DayPick
                key={day}
                label={`Day ${day}`}
                isSelected={repeat.dayOfMonth === day}
                onPress={() => set({ dayOfMonth: day })}
              >
                {day}
              </DayPick>
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
          <ClockField
            hour={repeat.hour}
            minute={repeat.minute}
            onChange={(hour, minute) => set({ hour, minute })}
          />
        </Field>
        {zone}
        {limit}
      </div>
      {forGaia && (
        <TextAction onPress={() => setIsCustom(true)}>
          Use a cron expression
        </TextAction>
      )}
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
  const limit = forGaia && isRepeating(when) && (
    <WhenEnds
      ends={when.ends}
      onChange={(ends) => onChange({ ...when, ends })}
    />
  );
  // A limit belongs to the repeat, so editing the days or the event keeps it.
  const change: Change = (next) =>
    onChange(
      isRepeating(next) && isRepeating(when)
        ? { ...next, ends: when.ends }
        : next,
    );
  const [mode, setMode] = useState<Mode>(() => modeOf(when) ?? "date");

  // What each mode held before you switched away, so looking at another one loses nothing.
  const [kept, setKept] = useState<Partial<Record<Mode, TaskWhen>>>({});

  const choose = (next: Mode) => {
    if (next === mode) return;
    const current = modeOf(when);
    if (current) setKept({ ...kept, [current]: when });
    setMode(next);
    const before = kept[next];
    if (before) onChange(before);
    // Repeating has a sensible default, so choosing it sets it; a date and an event are picked.
    else if (next === "repeat" && when.kind !== "schedule") {
      change(onSchedule(toCron(DEFAULT_REPEAT), getUserHomeTimezone()));
    }
  };

  return (
    <div className="w-full space-y-3">
      <Segmented
        label="When"
        options={modes.map((item) => {
          const Icon = WHEN_ICONS[item.kinds[0]];
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
        <RepeatPane
          when={when}
          onChange={change}
          forGaia={forGaia}
          limit={limit}
        />
      )}
      {mode === "event" && (
        <EventPane when={when} onChange={change} limit={limit} />
      )}

      {when.kind !== "anytime" && (
        <>
          <Separator className={separatorVariants({ surface: "raised" })} />
          <GaiaButton
            size="sm"
            variant="raised-ghost"
            shape="md"
            tone="muted"
            hoverTone="bright"
            onPress={onClear}
            className="h-9 w-full justify-start text-sm"
          >
            {forGaia ? "Only when I ask" : "No date"}
          </GaiaButton>
        </>
      )}
    </div>
  );
}

/**
 * The one "when" every task has: nothing, a date, a repeat, or (for GAIA) an app
 * event, a webhook or a watch. The row shows it in a line; the editor opens
 * under it, inside the sidebar.
 */
export default function WhenField({
  when,
  onChange,
  forGaia,
  runCount,
  isOpen: openFromOutside,
  onOpenChange,
}: {
  when: TaskWhen;
  onChange: Change;
  forGaia: boolean;
  /** occurrence_count, read against the limit on the Ends row. */
  runCount?: number;
  /** Set when something outside the row opens the editor, as a watch's fix does. */
  isOpen?: boolean;
  onOpenChange?: (isOpen: boolean) => void;
}) {
  const [isOwnOpen, setIsOwnOpen] = useState(false);
  const isOpen = openFromOutside ?? isOwnOpen;
  const setIsOpen = onOpenChange ?? setIsOwnOpen;
  // React Aria formats dates and times in the app's locale, not the browser's.
  const locale = useLocale();
  const ends = when.watch
    ? watchEndsLabel(when)
    : forGaia && isRepeating(when) && when.ends
      ? endsLabel(when.ends, runCount)
      : undefined;
  return (
    <>
      <PropertyRow label="When">
        <Popover isOpen={isOpen} onOpenChange={setIsOpen}>
          <GaiaButton
            size="sm"
            variant="property"
            inset="tight"
            aria-label="When"
            className="-ml-2 h-8 min-w-0 flex-1 justify-start text-sm"
          >
            <WhenValue when={when} />
          </GaiaButton>
          <Popover.Content
            placement="bottom end"
            offset={6}
            className={overlayVariants({
              surface: "raised",
              className: shapeVariants({
                shape: "xl",
                className: "w-[19rem] overflow-y-auto shadow-xl outline-none",
              }),
            })}
          >
            <I18nProvider locale={locale}>
              <div className="p-3 leading-5">
                <WhenEditor
                  when={when}
                  onChange={onChange}
                  forGaia={forGaia}
                  onClear={() => {
                    onChange(NO_WHEN);
                    setIsOpen(false);
                  }}
                />
              </div>
            </I18nProvider>
          </Popover.Content>
        </Popover>
      </PropertyRow>
      {ends && (
        <PropertyRow label="Ends">
          {/* The limit is set in the When editor, so its row opens that editor. */}
          <GaiaButton
            size="sm"
            variant="property"
            tone="bright"
            inset="tight"
            aria-label="Ends"
            onPress={() => setIsOpen(true)}
            className="-ml-2 h-8 min-w-0 justify-start text-sm tabular-nums"
          >
            {ends}
          </GaiaButton>
        </PropertyRow>
      )}
    </>
  );
}
