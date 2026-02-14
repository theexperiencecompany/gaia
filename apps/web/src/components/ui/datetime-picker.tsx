/**
 * Shadcn Datetime Picker with support for timezone, date and time selection, minimum and maximum date limits, and 12-hour format
 */
"use client";

import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  CalendarIcon,
  Cancel01Icon,
} from "@icons";
import {
  addHours,
  endOfDay,
  endOfHour,
  endOfMinute,
  format,
  parse,
  setHours,
  setMinutes,
  setSeconds,
  startOfDay,
  startOfHour,
  startOfMinute,
  subHours,
} from "date-fns";
import type * as React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DayPicker, type Matcher } from "react-day-picker";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export type CalendarProps = Omit<
  React.ComponentProps<typeof DayPicker>,
  "mode" | "selected" | "onSelect"
>;

const AM_VALUE = 0;
const PM_VALUE = 1;

export type DateTimePickerProps = {
  modal?: boolean;
  value: Date | undefined;
  onChange: (date: Date | undefined) => void;
  min?: Date;
  max?: Date;
  timezone?: string;
  disabled?: boolean;
  hideTime?: boolean;
  use12HourFormat?: boolean;
  clearable?: boolean;
  classNames?: {
    trigger?: string;
  };
  timePicker?: {
    hour?: boolean;
    minute?: boolean;
    second?: boolean;
  };
  renderTrigger?: (props: DateTimeRenderTriggerProps) => React.ReactNode;
};

export type DateTimeRenderTriggerProps = {
  value: Date | undefined;
  open: boolean;
  timezone?: string;
  disabled?: boolean;
  use12HourFormat?: boolean;
  setOpen: (open: boolean) => void;
};

export function DateTimePicker({
  value,
  onChange,
  renderTrigger,
  min,
  max,
  timezone,
  hideTime,
  use12HourFormat,
  disabled,
  clearable,
  classNames,
  timePicker,
  modal = false,
  ...props
}: DateTimePickerProps & CalendarProps) {
  const [open, setOpen] = useState(false);
  const initDate = useMemo(() => value || new Date(), [value]);

  const [month, setMonth] = useState<Date>(initDate);
  const [date, setDate] = useState<Date>(initDate);

  const minDate = useMemo(() => min, [min]);
  const maxDate = useMemo(() => max, [max]);

  const onDayChanged = useCallback(
    (d: Date) => {
      d.setHours(date.getHours(), date.getMinutes(), date.getSeconds());
      if (min && d < min) {
        d.setHours(min.getHours(), min.getMinutes(), min.getSeconds());
      }
      if (max && d > max) {
        d.setHours(max.getHours(), max.getMinutes(), max.getSeconds());
      }
      setDate(d);
    },
    [date, min, max],
  );

  const onSubmit = useCallback(() => {
    onChange(new Date(date));
    setOpen(false);
  }, [date, onChange]);

  useEffect(() => {
    if (open) {
      setDate(initDate);
      setMonth(initDate);
    }
  }, [open, initDate]);

  const displayValue = useMemo(() => {
    if (!open && !value) return value;
    return open ? date : initDate;
  }, [date, value, open, initDate]);

  const displayFormat = useMemo(() => {
    if (!displayValue) return "Pick a date";
    if (hideTime) {
      return format(displayValue, "MMM d, yyyy");
    }
    if (use12HourFormat) {
      return format(displayValue, "MMM d, yyyy h:mm a");
    }
    return format(displayValue, "MMM d, yyyy HH:mm");
  }, [displayValue, hideTime, use12HourFormat]);

  return (
    <Popover open={open} onOpenChange={setOpen} modal={modal}>
      <PopoverTrigger asChild>
        {renderTrigger ? (
          renderTrigger({
            value: displayValue,
            open,
            timezone,
            disabled,
            use12HourFormat,
            setOpen,
          })
        ) : (
          <div
            className={cn(
              "flex h-9 w-full cursor-pointer items-center rounded-xl bg-zinc-800/30 ps-3 pe-1 text-sm font-normal hover:bg-zinc-800/50",
              !displayValue && "text-zinc-500",
              (!clearable || !value) && "pe-3",
              disabled && "cursor-not-allowed opacity-50",
              classNames?.trigger,
            )}
          >
            <div className="flex flex-grow items-center text-zinc-400">
              <CalendarIcon className="mr-2 size-4" />
              {displayFormat}
            </div>
            {clearable && value && (
              <Button
                disabled={disabled}
                variant="ghost"
                size="sm"
                role="button"
                aria-label="Clear date"
                className="ms-1 size-6 p-1 hover:bg-zinc-700"
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  onChange(undefined);
                  setOpen(false);
                }}
              >
                <Cancel01Icon className="size-4 text-zinc-400" />
              </Button>
            )}
          </div>
        )}
      </PopoverTrigger>
      <PopoverContent className="w-auto rounded-2xl border-0 bg-zinc-800 p-0 shadow-xl">
        <div className="p-3">
          <DayPicker
            mode="single"
            selected={date}
            onSelect={(d) => d && onDayChanged(d)}
            month={month}
            onMonthChange={setMonth}
            disabled={
              [
                max ? { after: max } : undefined,
                min ? { before: min } : undefined,
              ].filter((m) => m !== undefined) as Matcher[]
            }
            classNames={{
              months: "flex flex-col sm:flex-row gap-2",
              month: "flex flex-col gap-4",
              caption: "flex justify-center pt-1 relative items-center w-full",
              caption_label: "text-sm font-medium text-zinc-200",
              nav: "flex items-center gap-1",
              nav_button: cn(
                buttonVariants({ variant: "ghost" }),
                "size-7 bg-transparent p-0 opacity-50 hover:opacity-100 hover:bg-zinc-700",
              ),
              nav_button_previous: "absolute left-1",
              nav_button_next: "absolute right-1",
              day: cn(
                buttonVariants({ variant: "ghost" }),
                "size-9 p-0 font-normal cursor-pointer transition-colors",
                "hover:bg-zinc-700 hover:text-zinc-100",
                "text-zinc-300",
              ),
            }}
            showOutsideDays={true}
            components={{
              IconLeft: ({ ...props }) => (
                <ArrowLeft01Icon className="size-4 text-zinc-400" {...props} />
              ),
              IconRight: ({ ...props }) => (
                <ArrowRight01Icon className="size-4 text-zinc-400" {...props} />
              ),
            }}
            {...props}
          />
        </div>
        {!hideTime && (
          <div className="p-3 pt-0">
            <TimePickerInline
              timePicker={timePicker}
              value={date}
              onChange={setDate}
              use12HourFormat={use12HourFormat}
              min={minDate}
              max={maxDate}
            />
          </div>
        )}
        <div className="flex items-center justify-between p-3 pt-2">
          {timezone && (
            <div className="text-xs text-zinc-500">
              <span className="font-medium text-zinc-400">{timezone}</span>
            </div>
          )}
          <Button
            size="sm"
            className="ml-auto bg-primary text-primary-foreground hover:bg-primary/90"
            onClick={onSubmit}
          >
            Done
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

interface TimeOption {
  value: number;
  label: string;
  disabled: boolean;
}

function TimePickerInline({
  value,
  onChange,
  use12HourFormat,
  min,
  max,
  timePicker,
}: {
  use12HourFormat?: boolean;
  value: Date;
  onChange: (date: Date) => void;
  min?: Date;
  max?: Date;
  timePicker?: DateTimePickerProps["timePicker"];
}) {
  const formatStr = useMemo(
    () =>
      use12HourFormat
        ? "yyyy-MM-dd hh:mm:ss.SSS a xxxx"
        : "yyyy-MM-dd HH:mm:ss.SSS xxxx",
    [use12HourFormat],
  );
  const [ampm, setAmpm] = useState(
    format(value, "a") === "AM" ? AM_VALUE : PM_VALUE,
  );
  const [hour, setHour] = useState(
    use12HourFormat ? +format(value, "hh") : value.getHours(),
  );
  const [minute, setMinute] = useState(value.getMinutes());
  const [second] = useState(value.getSeconds());

  useEffect(() => {
    const newTime = buildTime({
      use12HourFormat,
      value,
      formatStr,
      hour,
      minute,
      second,
      ampm,
    });
    if (newTime.getTime() !== value.getTime()) {
      onChange(newTime);
    }
  }, [hour, minute, second, ampm]);

  const _hourIn24h = useMemo(() => {
    return use12HourFormat ? (hour % 12) + ampm * 12 : hour;
  }, [hour, use12HourFormat, ampm]);

  const hours: TimeOption[] = useMemo(
    () =>
      Array.from({ length: use12HourFormat ? 12 : 24 }, (_, i) => {
        let disabled = false;
        const hourValue = use12HourFormat ? (i === 0 ? 12 : i) : i;
        const hDate = setHours(value, use12HourFormat ? i + ampm * 12 : i);
        const hStart = startOfHour(hDate);
        const hEnd = endOfHour(hDate);
        if (min && hEnd < min) disabled = true;
        if (max && hStart > max) disabled = true;
        return {
          value: hourValue,
          label: hourValue.toString().padStart(2, "0"),
          disabled,
        };
      }),
    [value, min, max, use12HourFormat, ampm],
  );

  const minutes: TimeOption[] = useMemo(() => {
    const anchorDate = setHours(value, _hourIn24h);
    return Array.from({ length: 60 }, (_, i) => {
      let disabled = false;
      const mDate = setMinutes(anchorDate, i);
      const mStart = startOfMinute(mDate);
      const mEnd = endOfMinute(mDate);
      if (min && mEnd < min) disabled = true;
      if (max && mStart > max) disabled = true;
      return {
        value: i,
        label: i.toString().padStart(2, "0"),
        disabled,
      };
    });
  }, [value, min, max, _hourIn24h]);

  const ampmOptions = useMemo(() => {
    const startD = startOfDay(value);
    const endD = endOfDay(value);
    return [
      { value: AM_VALUE, label: "AM" },
      { value: PM_VALUE, label: "PM" },
    ].map((v) => {
      let disabled = false;
      const start = addHours(startD, v.value * 12);
      const end = subHours(endD, (1 - v.value) * 12);
      if (min && end < min) disabled = true;
      if (max && start > max) disabled = true;
      return { ...v, disabled };
    });
  }, [value, min, max]);

  const hourRef = useRef<HTMLDivElement>(null);
  const minuteRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    hourRef.current?.scrollIntoView({ behavior: "auto", block: "center" });
    minuteRef.current?.scrollIntoView({ behavior: "auto", block: "center" });
  }, []);

  return (
    <div className="flex gap-2">
      {(!timePicker || timePicker.hour) && (
        <ScrollArea className="h-48 flex-1">
          <div className="flex flex-col gap-1 p-1">
            {hours.map((v) => (
              <div key={v.value} ref={v.value === hour ? hourRef : undefined}>
                <Button
                  variant={v.value === hour ? "default" : "ghost"}
                  size="sm"
                  disabled={v.disabled}
                  className={cn(
                    "w-full justify-center",
                    v.value === hour && "bg-primary text-primary-foreground",
                  )}
                  onClick={() => setHour(v.value)}
                >
                  {v.label}
                </Button>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
      {(!timePicker || timePicker.minute) && (
        <ScrollArea className="h-48 flex-1">
          <div className="flex flex-col gap-1 p-1">
            {minutes.map((v) => (
              <div
                key={v.value}
                ref={v.value === minute ? minuteRef : undefined}
              >
                <Button
                  variant={v.value === minute ? "default" : "ghost"}
                  size="sm"
                  disabled={v.disabled}
                  className={cn(
                    "w-full justify-center",
                    v.value === minute && "bg-primary text-primary-foreground",
                  )}
                  onClick={() => setMinute(v.value)}
                >
                  {v.label}
                </Button>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}
      {use12HourFormat && (
        <ScrollArea className="h-48 w-20">
          <div className="flex flex-col gap-1 p-1">
            {ampmOptions.map((v) => (
              <Button
                key={v.value}
                variant={v.value === ampm ? "default" : "ghost"}
                size="sm"
                disabled={v.disabled}
                className={cn(
                  "w-full justify-center",
                  v.value === ampm && "bg-primary text-primary-foreground",
                )}
                onClick={() => setAmpm(v.value)}
              >
                {v.label}
              </Button>
            ))}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}

interface BuildTimeOptions {
  use12HourFormat?: boolean;
  value: Date;
  formatStr: string;
  hour: number;
  minute: number;
  second: number;
  ampm: number;
}

function buildTime(options: BuildTimeOptions) {
  const { use12HourFormat, value, formatStr, hour, minute, second, ampm } =
    options;
  let date: Date;
  if (use12HourFormat) {
    const dateStrRaw = format(value, formatStr);
    let dateStr =
      dateStrRaw.slice(0, 11) +
      hour.toString().padStart(2, "0") +
      dateStrRaw.slice(13);
    dateStr =
      dateStr.slice(0, 14) +
      minute.toString().padStart(2, "0") +
      dateStr.slice(16);
    dateStr =
      dateStr.slice(0, 17) +
      second.toString().padStart(2, "0") +
      dateStr.slice(19);
    dateStr =
      dateStr.slice(0, 24) +
      (ampm === AM_VALUE ? "AM" : "PM") +
      dateStr.slice(26);
    date = parse(dateStr, formatStr, value);
  } else {
    date = setHours(setMinutes(setSeconds(value, second), minute), hour);
  }
  return date;
}
