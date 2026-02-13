"use client";

import { Input } from "@heroui/input";
import { CalendarIcon } from "@icons";
import { parseDate } from "chrono-node";
import React, { useId } from "react";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  formatDateLocal,
  formatDateTimeLocal,
  fromDateTimeLocalString,
  getEndOfDay,
  getStartOfDay,
  toDateTimeLocalString,
} from "@/utils/date/dateTimeLocalUtils";

interface NaturalLanguageDateInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  isAllDay?: boolean;
  className?: string;
}

export const NaturalLanguageDateInput: React.FC<
  NaturalLanguageDateInputProps
> = ({
  label,
  value,
  onChange,
  placeholder,
  isAllDay = false,
  className = "",
}) => {
  const [inputValue, setInputValue] = React.useState("");
  const [isPickerOpen, setIsPickerOpen] = React.useState(false);
  const [selectedDate, setSelectedDate] = React.useState<Date | undefined>(
    value ? fromDateTimeLocalString(value) : undefined,
  );
  const [selectedHour, setSelectedHour] = React.useState<number>(
    value ? fromDateTimeLocalString(value).getHours() : 9,
  );
  const [selectedMinute, setSelectedMinute] = React.useState<number>(
    value ? fromDateTimeLocalString(value).getMinutes() : 0,
  );

  React.useEffect(() => {
    if (value) {
      const d = fromDateTimeLocalString(value);
      if (!Number.isNaN(d.getTime())) {
        setSelectedDate(d);
        setSelectedHour(d.getHours());
        setSelectedMinute(d.getMinutes());
      }
    }
  }, [value]);

  const formatDateDisplay = (dateStr: string) => {
    if (!dateStr) return "";

    if (isAllDay) {
      return formatDateLocal(dateStr);
    }
    return formatDateTimeLocal(dateStr);
  };

  const handleInputChange = (text: string) => {
    setInputValue(text);

    if (!text.trim()) return;

    const parsed = parseDate(text, undefined, { forwardDate: true });
    if (parsed && !Number.isNaN(parsed.getTime())) {
      if (isAllDay) {
        onChange(getStartOfDay(parsed));
      } else {
        onChange(toDateTimeLocalString(parsed));
      }
    }
  };

  const handleDaySelect = (date: Date | undefined) => {
    if (date && !Number.isNaN(date.getTime())) {
      setSelectedDate(date);
      if (isAllDay) {
        onChange(getStartOfDay(date));
        setInputValue("");
        setIsPickerOpen(false);
      }
    }
  };

  const handleTimeConfirm = () => {
    if (selectedDate) {
      const newDate = new Date(selectedDate);
      newDate.setHours(selectedHour, selectedMinute, 0, 0);
      onChange(toDateTimeLocalString(newDate));
      setInputValue("");
      setIsPickerOpen(false);
    }
  };

  const hours = Array.from({ length: 24 }, (_, i) => i);
  const minutes = Array.from({ length: 60 }, (_, i) => i);
  const baseId = useId();

  return (
    <div className={`space-y-2 ${className}`}>
      <label className="text-xs text-zinc-500" htmlFor={baseId}>
        {label}
      </label>
      <Popover open={isPickerOpen} onOpenChange={setIsPickerOpen}>
        <div className="relative">
          <Input
            id={baseId}
            value={inputValue}
            onChange={(e) => handleInputChange(e.target.value)}
            placeholder={placeholder}
            classNames={{
              input: "text-zinc-200 placeholder:text-zinc-600 pr-10",
              inputWrapper:
                "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
            }}
            endContent={
              <PopoverTrigger asChild>
                <button
                  className="flex items-center justify-center text-zinc-500 transition-colors hover:text-zinc-300"
                  aria-label="Toggle calendar picker"
                  type="button"
                >
                  <CalendarIcon className="size-4" />
                </button>
              </PopoverTrigger>
            }
          />
        </div>
        <PopoverContent className="w-auto overflow-hidden rounded-2xl border-0 bg-zinc-800 p-0 shadow-xl">
          <div className="p-3">
            <Calendar
              mode="single"
              selected={selectedDate}
              onSelect={handleDaySelect}
              className="bg-zinc-800"
            />
          </div>
          {!isAllDay && (
            <>
              <div className="flex gap-2 p-3 pt-0">
                <ScrollArea className="h-48 flex-1">
                  <div className="flex flex-col gap-1 p-1">
                    {hours.map((h) => (
                      <button
                        type="button"
                        key={h}
                        onClick={() => setSelectedHour(h)}
                        className={cn(
                          "w-full rounded-lg px-3 py-1.5 text-sm transition-colors",
                          h === selectedHour
                            ? "bg-primary text-primary-foreground"
                            : "text-zinc-300 hover:bg-zinc-700",
                        )}
                      >
                        {h.toString().padStart(2, "0")}
                      </button>
                    ))}
                  </div>
                </ScrollArea>
                <ScrollArea className="h-48 flex-1">
                  <div className="flex flex-col gap-1 p-1">
                    {minutes.map((m) => (
                      <button
                        type="button"
                        key={m}
                        onClick={() => setSelectedMinute(m)}
                        className={cn(
                          "w-full rounded-lg px-3 py-1.5 text-sm transition-colors",
                          m === selectedMinute
                            ? "bg-primary text-primary-foreground"
                            : "text-zinc-300 hover:bg-zinc-700",
                        )}
                      >
                        {m.toString().padStart(2, "0")}
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              </div>
              <div className="flex items-center justify-end p-3 pt-2">
                <button
                  type="button"
                  onClick={handleTimeConfirm}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  Done
                </button>
              </div>
            </>
          )}
        </PopoverContent>
      </Popover>
      {value && (
        <div className="px-1 text-xs text-zinc-500">
          {formatDateDisplay(value)}
        </div>
      )}
    </div>
  );
};

interface NaturalLanguageDateRangeInputProps {
  label: string;
  startValue: string;
  endValue: string;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
  placeholder: string;
  className?: string;
}

export const NaturalLanguageDateRangeInput: React.FC<
  NaturalLanguageDateRangeInputProps
> = ({
  label,
  startValue,
  endValue,
  onStartChange,
  onEndChange,
  placeholder,
  className = "",
}) => {
  const [inputValue, setInputValue] = React.useState("");
  const [isPickerOpen, setIsPickerOpen] = React.useState(false);
  const [range, setRange] = React.useState<{
    from: Date | undefined;
    to: Date | undefined;
  }>({
    from: startValue ? fromDateTimeLocalString(startValue) : undefined,
    to: endValue ? fromDateTimeLocalString(endValue) : undefined,
  });

  React.useEffect(() => {
    setRange({
      from: startValue ? fromDateTimeLocalString(startValue) : undefined,
      to: endValue ? fromDateTimeLocalString(endValue) : undefined,
    });
  }, [startValue, endValue]);

  const formatDateDisplay = (dateStr: string) => {
    if (!dateStr) return "";
    return formatDateLocal(dateStr);
  };

  const handleInputChange = (text: string) => {
    setInputValue(text);

    if (!text.trim()) return;

    const parts = text.toLowerCase().split(/\s+to\s+|\s+-\s+/);
    const parsed = parseDate(text, undefined, { forwardDate: true });

    if (parsed && !Number.isNaN(parsed.getTime())) {
      onStartChange(getStartOfDay(parsed));

      if (parts.length === 2) {
        const endParsed = parseDate(parts[1], parsed);
        if (endParsed && !Number.isNaN(endParsed.getTime())) {
          onEndChange(getEndOfDay(endParsed));
        }
      } else {
        onEndChange(getEndOfDay(parsed));
      }
    }
  };

  const handleRangeSelect = (
    selectedRange: { from?: Date; to?: Date } | undefined,
  ) => {
    if (selectedRange?.from) {
      onStartChange(getStartOfDay(selectedRange.from));
      setInputValue("");

      if (selectedRange.to) {
        onEndChange(getEndOfDay(selectedRange.to));
        setIsPickerOpen(false);
      }
    }
  };

  const baseId = useId();

  return (
    <div className={`space-y-2 ${className}`}>
      <label className="text-sm font-medium text-zinc-400" htmlFor={baseId}>
        {label}
      </label>
      <Popover open={isPickerOpen} onOpenChange={setIsPickerOpen}>
        <div className="relative">
          <Input
            id={baseId}
            value={inputValue}
            onChange={(e) => handleInputChange(e.target.value)}
            placeholder={placeholder}
            classNames={{
              input: "text-zinc-200 placeholder:text-zinc-600 pr-10",
              inputWrapper:
                "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
            }}
            endContent={
              <PopoverTrigger asChild>
                <button
                  className="flex items-center justify-center text-zinc-500 transition-colors hover:text-zinc-300"
                  aria-label="Toggle calendar picker"
                  type="button"
                >
                  <CalendarIcon className="size-4" />
                </button>
              </PopoverTrigger>
            }
          />
        </div>
        <PopoverContent className="w-auto overflow-hidden rounded-2xl border-0 bg-zinc-800 p-1 shadow-xl">
          <Calendar
            mode="range"
            selected={range}
            onSelect={handleRangeSelect}
            numberOfMonths={2}
            className="bg-zinc-800"
          />
        </PopoverContent>
      </Popover>
      {(startValue || endValue) && (
        <div className="px-1 text-xs text-zinc-500">
          {startValue && formatDateDisplay(startValue)}
          {startValue && endValue && " → "}
          {endValue && startValue !== endValue && formatDateDisplay(endValue)}
        </div>
      )}
    </div>
  );
};
