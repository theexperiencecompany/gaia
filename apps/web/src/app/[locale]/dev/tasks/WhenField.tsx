"use client";

import {
  Calendar,
  Input,
  InputGroup,
  Popover,
  Separator,
  TextArea,
  TimeField,
} from "@heroui/react";
import { FilterHorizontalIcon, Search01Icon, Tick02Icon } from "@icons";
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
import { AppIcon } from "./AppIcons";
import { APP_NAMES, DEMO_TRIGGERS } from "./demoTriggers";
import { PropertyRow } from "./PropertyRow";
import { WHEN_ICONS } from "./TaskChips";
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

/** Every field in the editor: 36px tall, 12px corners, one step darker than the popover. */
const EDITOR_FIELD = inputVariants({ variant: "sunken" });

const calendar = calendarVariants();

/** A quiet text action under a field, on the same 4px inset as the field labels. */
function TextAction({
  onPress,
  children,
}: {
  onPress: () => void;
  children: ReactNode;
}) {
  return (
    <GaiaButton
      size="sm"
      variant="text"
      inset="snug"
      tone="faint"
      hoverTone="bright"
      onPress={onPress}
      className="h-7 min-w-0 justify-start text-[13px]"
    >
      {children}
    </GaiaButton>
  );
}

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
    <fieldset
      aria-label={label}
      className="mx-0 flex h-9 min-w-0 gap-1 rounded-xl border-0 bg-zinc-900 p-1"
    >
      {options.map((option) => {
        const isOn = option.key === value;
        return (
          <GaiaButton
            key={option.key}
            size="sm"
            variant={isOn ? "default-solid" : "text"}
            tone={isOn ? "strong" : "muted"}
            hoverTone={isOn ? "none" : "bright"}
            inset="tight"
            aria-pressed={isOn}
            onPress={() => onChange(option.key)}
            className="h-7 min-w-0 flex-1 gap-1.5 text-[13px] font-medium"
          >
            {option.icon}
            {option.label}
          </GaiaButton>
        );
      })}
    </fieldset>
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
          value={cron}
          onChange={(event) =>
            onChange(onSchedule(event.target.value, timezone))
          }
          placeholder="0 9 * * 1-5"
          className={inputVariants({
            variant: "sunken",
            size: "sm",
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
      </div>
      {forGaia && (
        <TextAction onPress={() => setIsCustom(true)}>
          Use a cron expression
        </TextAction>
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
        <GaiaButton
          size="sm"
          variant="sunken"
          shape="md"
          tone="strong"
          aria-label="Change the event"
          onPress={() => setIsChoosing(true)}
          className="h-9 w-full justify-start gap-2 text-sm"
        >
          <AppIcon id={selected.app} size={16} />
          <span className="truncate">{selected.name}</span>
          <span className="ml-auto text-[13px] text-zinc-500">Change</span>
        </GaiaButton>
        <div>
          <p className="px-1 pb-1.5 text-[13px] text-zinc-500">Only when</p>
          <TextArea
            aria-label="Only when"
            value={when.condition ?? ""}
            onChange={(event) =>
              onChange(onEvent(selected.slug, event.target.value))
            }
            placeholder="It has an invoice attached"
            rows={2}
            className={inputVariants({
              variant: "sunken",
              placeholder: "subtle",
              className: toneVariants({
                tone: "white",
                className: "block w-full resize-none text-sm leading-5",
              }),
            })}
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
      <InputGroup
        className={inputVariants({ variant: "sunken", className: "w-full" })}
      >
        <InputGroup.Prefix>
          <Search01Icon className="size-4 shrink-0 text-zinc-500" />
        </InputGroup.Prefix>
        <InputGroup.Input
          autoFocus
          aria-label="Search events"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search apps and events"
          className={toneVariants({ tone: "white", className: "text-sm" })}
        />
      </InputGroup>
      <div className="-mx-1 max-h-72 overflow-y-auto px-1">
        {apps.map((app) => (
          <section key={app}>
            <h4 className="px-3 pt-3 pb-1 text-xs text-zinc-500">
              {APP_NAMES[app]}
            </h4>
            {matches
              .filter((item) => item.app === app)
              .map((item) => (
                <GaiaButton
                  key={item.slug}
                  size="sm"
                  variant="raised-ghost"
                  shape="md"
                  tone="bright"
                  onPress={() => {
                    onChange(onEvent(item.slug, when.condition));
                    setIsChoosing(false);
                    setQuery("");
                  }}
                  className="h-9 w-full justify-start gap-2 text-sm"
                >
                  <AppIcon id={item.app} size={15} />
                  {item.name}
                  {item.slug === when.trigger && (
                    <Tick02Icon className="ml-auto size-4 text-zinc-400" />
                  )}
                </GaiaButton>
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
  // React Aria formats dates and times in the app's locale, not the browser's.
  const locale = useLocale();
  return (
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
              className: "w-[19rem] shadow-xl outline-none",
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
  );
}
