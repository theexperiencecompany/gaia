"use client";

import { format } from "date-fns";
import * as React from "react";

import { Button } from "@/components/ui/shadcn/button";
import { Calendar } from "@/components/ui/shadcn/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/shadcn/popover";
import { ScrollArea, ScrollBar } from "@/components/ui/shadcn/scroll-area";
import { cn } from "@/lib/utils";

interface DateTimePickerProps {
  date?: Date;
  onDateChange: (date: Date | undefined) => void;
  placeholder?: string;
}

export function DateTimePicker({
  date,
  onDateChange,
  placeholder = "MM/DD/YYYY hh:mm aa",
}: DateTimePickerProps) {
  const [isOpen, setIsOpen] = React.useState(false);

  const hours = Array.from({ length: 12 }, (_, i) => i + 1);

  const handleDateSelect = React.useCallback(
    (selectedDate: Date | undefined) => {
      if (selectedDate) {
        const newDate = date ? new Date(date) : new Date();
        newDate.setFullYear(
          selectedDate.getFullYear(),
          selectedDate.getMonth(),
          selectedDate.getDate(),
        );
        onDateChange(newDate);
      }
    },
    [date, onDateChange],
  );

  const handleTimeChange = React.useCallback(
    (type: "hour" | "minute" | "ampm", value: string) => {
      const currentDate = date || new Date();
      const newDate = new Date(currentDate);

      if (type === "hour") {
        const hour = parseInt(value);
        const currentHours = newDate.getHours();
        const isPM = currentHours >= 12;
        newDate.setHours((hour % 12) + (isPM ? 12 : 0));
      } else if (type === "minute") {
        newDate.setMinutes(parseInt(value));
      } else if (type === "ampm") {
        const currentHours = newDate.getHours();
        if (value === "PM" && currentHours < 12) {
          newDate.setHours(currentHours + 12);
        } else if (value === "AM" && currentHours >= 12) {
          newDate.setHours(currentHours - 12);
        }
      }
      onDateChange(newDate);
    },
    [date, onDateChange],
  );

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "w-full justify-start rounded-xl border-0 bg-zinc-800/30 text-left font-normal text-zinc-400 hover:bg-zinc-800/50",
            !date && "text-zinc-500",
          )}
        >
          {date ? (
            format(date, "MM/dd/yyyy hh:mm aa")
          ) : (
            <span>{placeholder}</span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto overflow-hidden rounded-2xl border-0 bg-zinc-800 p-1 shadow-xl">
        <div className="sm:flex">
          <Calendar
            mode="single"
            selected={date}
            onSelect={handleDateSelect}
            initialFocus
            className="bg-zinc-800"
            disabled={false}
          />
          <div className="flex flex-col divide-y divide-zinc-800 sm:h-[300px] sm:flex-row sm:divide-x sm:divide-y-0">
            <ScrollArea className="w-64 sm:w-auto">
              <div className="flex p-2 sm:flex-col">
                {hours.reverse().map((hour) => (
                  <Button
                    key={hour}
                    size="icon"
                    variant={
                      date && date.getHours() % 12 === hour % 12
                        ? "default"
                        : "ghost"
                    }
                    className="aspect-square shrink-0 sm:w-full"
                    onClick={() => handleTimeChange("hour", hour.toString())}
                  >
                    {hour}
                  </Button>
                ))}
              </div>
              <ScrollBar orientation="horizontal" className="sm:hidden" />
            </ScrollArea>
            <ScrollArea className="w-64 sm:w-auto">
              <div className="flex p-2 sm:flex-col">
                {Array.from({ length: 12 }, (_, i) => i * 5).map((minute) => (
                  <Button
                    key={minute}
                    size="icon"
                    variant={
                      date && date.getMinutes() === minute ? "default" : "ghost"
                    }
                    className="aspect-square shrink-0 sm:w-full"
                    onClick={() =>
                      handleTimeChange("minute", minute.toString())
                    }
                  >
                    {minute.toString().padStart(2, "0")}
                  </Button>
                ))}
              </div>
              <ScrollBar orientation="horizontal" className="sm:hidden" />
            </ScrollArea>
            <ScrollArea className="">
              <div className="flex p-2 sm:flex-col">
                {["AM", "PM"].map((ampm) => (
                  <Button
                    key={ampm}
                    size="icon"
                    variant={
                      date &&
                      ((ampm === "AM" && date.getHours() < 12) ||
                        (ampm === "PM" && date.getHours() >= 12))
                        ? "default"
                        : "ghost"
                    }
                    className="aspect-square shrink-0 sm:w-full"
                    onClick={() => handleTimeChange("ampm", ampm)}
                  >
                    {ampm}
                  </Button>
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
