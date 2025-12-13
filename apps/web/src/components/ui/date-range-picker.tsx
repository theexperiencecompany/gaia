"use client";

import { formatDateRange } from "little-date";
import { useState } from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ArrowDown01Icon } from "@/icons";
import { cn } from "@/lib/utils";

interface DateRangePickerProps {
  from?: Date;
  to?: Date;
  onDateChange: (from: Date | undefined, to: Date | undefined) => void;
  placeholder?: string;
  label?: string;
  className?: string;
}

export function DateRangePicker({
  from,
  to,
  onDateChange,
  placeholder = "Pick a date",
  label,
  className,
}: DateRangePickerProps) {
  const [range, setRange] = useState<DateRange | undefined>(
    from ? { from, to } : undefined,
  );

  const handleSelect = (selectedRange: DateRange | undefined) => {
    setRange(selectedRange);
    if (selectedRange?.from) {
      onDateChange(selectedRange.from, selectedRange.to);
    } else {
      onDateChange(undefined, undefined);
    }
  };

  return (
    <div className={cn("w-full space-y-2", className)}>
      {label && (
        <Label
          htmlFor="date-range"
          className="px-1 text-sm font-medium text-zinc-400"
        >
          {label}
        </Label>
      )}
      <Popover>
        <PopoverTrigger asChild>
          <Button
            variant="ghost"
            id="date-range"
            className={cn(
              "w-full justify-between rounded-xl bg-zinc-800/30 text-left font-normal text-zinc-400 hover:bg-zinc-800/50",
              !range?.from && "text-zinc-500",
            )}
          >
            {range?.from && range?.to
              ? formatDateRange(range.from, range.to, {
                  includeTime: false,
                })
              : placeholder}
            <ArrowDown01Icon className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-auto overflow-hidden rounded-2xl border-0 bg-zinc-800 p-1 shadow-xl"
          align="start"
        >
          <Calendar
            mode="range"
            selected={range}
            onSelect={handleSelect}
            numberOfMonths={2}
            className="bg-zinc-800"
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
