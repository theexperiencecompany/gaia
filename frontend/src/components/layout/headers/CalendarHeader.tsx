"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Select, SelectItem } from "@heroui/select";
import { ChevronLeft, ChevronRight } from "lucide-react";
import React, { useState } from "react";

import { CalendarAdd01Icon, CalendarIcon } from "@/components/shared";
import {
  useCalendarSelectedDate,
  useCreateEventAction,
  useGoToNextDay,
  useGoToPreviousDay,
  useGoToToday,
  useHandleDateChange,
} from "@/stores/calendarStore";

import { SidebarHeaderButton } from "./HeaderManager";
import { HeaderTitle } from "./HeaderTitle";

export default function CalendarHeader() {
  const [showMonthYearPicker, setShowMonthYearPicker] = useState(false);
  const selectedDate = useCalendarSelectedDate();
  const handleDateChange = useHandleDateChange();
  const goToPreviousDay = useGoToPreviousDay();
  const goToNextDay = useGoToNextDay();
  const goToToday = useGoToToday();
  const createEventAction = useCreateEventAction();

  const monthYear = selectedDate.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });

  const handleMonthYearChange = (month: number, year: number) => {
    const newDate = new Date(year, month, selectedDate.getDate());
    handleDateChange(newDate);
    setShowMonthYearPicker(false);
  };
  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-3">
        <HeaderTitle
          icon={<CalendarIcon width={20} height={20} color={undefined} />}
          text="Calendar"
        />

        <Popover
          isOpen={showMonthYearPicker}
          onOpenChange={setShowMonthYearPicker}
        >
          <PopoverTrigger>
            <Button variant="flat" size="sm">
              {monthYear}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-fit p-0 px-3">
            <div className="p-4">
              <h3 className="mb-3 text-sm font-medium text-zinc-300">
                Select Month & Year
              </h3>

              <div className="mb-3">
                <Select
                  label="Year"
                  selectedKeys={[selectedDate.getFullYear().toString()]}
                  onSelectionChange={(keys) => {
                    const year = parseInt(Array.from(keys)[0] as string);
                    handleMonthYearChange(selectedDate.getMonth(), year);
                  }}
                  className="mb-3"
                  classNames={{
                    trigger: "bg-zinc-900 border-zinc-600",
                    value: "text-zinc-300",
                    label: "text-zinc-400",
                  }}
                >
                  {Array.from({ length: 11 }, (_, i) => {
                    const year = new Date().getFullYear() - 5 + i;
                    return (
                      <SelectItem key={year.toString()}>
                        {year.toString()}
                      </SelectItem>
                    );
                  })}
                </Select>
              </div>

              <div>
                <label className="mb-2 block text-xs text-zinc-400">
                  Month
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {Array.from({ length: 12 }, (_, i) => {
                    const monthName = new Date(2025, i, 1).toLocaleDateString(
                      "en-US",
                      { month: "short" },
                    );
                    const isCurrentMonth = i === selectedDate.getMonth();
                    return (
                      <Button
                        key={i}
                        size="sm"
                        variant={isCurrentMonth ? "solid" : "flat"}
                        color={isCurrentMonth ? "primary" : "default"}
                        className={`${
                          isCurrentMonth
                            ? ""
                            : "bg-zinc-900 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300"
                        }`}
                        onPress={() =>
                          handleMonthYearChange(i, selectedDate.getFullYear())
                        }
                      >
                        {monthName}
                      </Button>
                    );
                  })}
                </div>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>

      <div className="relative flex items-center gap-2">
        <div className="flex items-center">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={goToPreviousDay}
          >
            <ChevronLeft className="h-5 w-5 text-zinc-400" />
          </Button>

          <Button isIconOnly size="sm" variant="light" onPress={goToNextDay}>
            <ChevronRight className="h-5 w-5 text-zinc-400" />
          </Button>
          <Button variant="flat" onPress={goToToday} size="sm" className="ml-">
            Today
          </Button>
        </div>

        {createEventAction && (
          <SidebarHeaderButton
            aria-label="Create new calendar event"
            tooltip="Create new calendar event"
            onClick={createEventAction}
          >
            <CalendarAdd01Icon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        )}
      </div>
    </div>
  );
}
