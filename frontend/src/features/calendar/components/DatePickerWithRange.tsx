"use client";

import * as React from "react";
import { ArrowRight, Calendar as CalendarIcon } from "lucide-react";
import { format } from "date-fns";
import type { DateRange } from "react-day-picker";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/shadcn/button";
import { Calendar } from "@/components/ui/shadcn/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/shadcn/popover";

interface DatePickerWithRangeProps {
  from?: Date;
  to?: Date;
  onDateChange: (from: Date | undefined, to: Date | undefined) => void;
  placeholder?: string;
}

export function DatePickerWithRange({
  from,
  to,
  onDateChange,
  placeholder = "Pick a date",
}: DatePickerWithRangeProps) {
  const [isOpen, setIsOpen] = React.useState(false);

  const handleSelect = React.useCallback(
    (range: DateRange | undefined) => {
      if (range?.from) {
        onDateChange(range.from, range.to);
      } else {
        onDateChange(undefined, undefined);
      }
    },
    [onDateChange],
  );

  const selectedRange = React.useMemo<DateRange | undefined>(() => {
    if (from) {
      return { from, to };
    }
    return undefined;
  }, [from, to]);

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "w-full justify-between rounded-xl border-0 bg-zinc-800/30 text-left font-normal text-zinc-400 hover:bg-zinc-800/50",
            !from && "text-zinc-500",
          )}
        >
          <div className="flex w-full items-center justify-between gap-2">
            {from ? (
              to ? (
                <>
                  <span>{format(from, "LLL dd, y")}</span>
                  <ArrowRight
                    className="min-h-4 min-w-4 shrink-0 text-zinc-500"
                    width={16}
                    height={16}
                  />
                  <span>{format(to, "LLL dd, y")}</span>
                </>
              ) : (
                format(from, "LLL dd, y")
              )
            ) : (
              <span>{placeholder}</span>
            )}
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-auto rounded-2xl border-0 bg-zinc-800 p-1 shadow-xl"
        align="start"
      >
        <Calendar
          initialFocus
          mode="range"
          defaultMonth={from}
          selected={selectedRange}
          onSelect={handleSelect}
          numberOfMonths={2}
          className="bg-zinc-800"
          disabled={false}
        />
      </PopoverContent>
    </Popover>
  );
}
