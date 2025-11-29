"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/react";
import { Select, SelectItem } from "@heroui/select";
import { useHotkeys } from "react-hotkeys-hook";

import { CalendarAdd01Icon, CalendarIcon } from "@/components/shared";
import { ArrowLeft01Icon, ArrowRight01Icon } from "@/icons";
import {
  useCreateEventAction,
  useDaysToShow,
  useGoToNextDay,
  useGoToPreviousDay,
  useGoToToday,
  useSetDaysToShow,
  useVisibleMonth,
  useVisibleYear,
} from "@/stores/calendarStore";

import { SidebarHeaderButton } from "./HeaderManager";
import { HeaderTitle } from "./HeaderTitle";

const dayOptions = [
  { value: "1", label: "1 Day", kbd: "1" },
  { value: "2", label: "2 Days", kbd: "2" },
  { value: "3", label: "3 Days", kbd: "3" },
  { value: "4", label: "4 Days", kbd: "4" },
  { value: "5", label: "5 Days", kbd: "5" },
  { value: "6", label: "6 Days", kbd: "6" },
  { value: "7", label: "Week", kbd: "7" },
  { value: "8", label: "8 Days", kbd: "8" },
  { value: "9", label: "9 Days", kbd: "9" },
];

export default function CalendarHeader() {
  const daysToShow = useDaysToShow();
  const goToPreviousDay = useGoToPreviousDay();
  const goToNextDay = useGoToNextDay();
  const goToToday = useGoToToday();
  const createEventAction = useCreateEventAction();
  const setDaysToShow = useSetDaysToShow();
  const visibleMonth = useVisibleMonth();
  const visibleYear = useVisibleYear();

  // Hotkeys for number keys 1-9 to set days view
  useHotkeys("1", () => setDaysToShow(1), { enableOnFormTags: false });
  useHotkeys("2", () => setDaysToShow(2), { enableOnFormTags: false });
  useHotkeys("3", () => setDaysToShow(3), { enableOnFormTags: false });
  useHotkeys("4", () => setDaysToShow(4), { enableOnFormTags: false });
  useHotkeys("5", () => setDaysToShow(5), { enableOnFormTags: false });
  useHotkeys("6", () => setDaysToShow(6), { enableOnFormTags: false });
  useHotkeys("7", () => setDaysToShow(7), { enableOnFormTags: false });
  useHotkeys("8", () => setDaysToShow(8), { enableOnFormTags: false });
  useHotkeys("9", () => setDaysToShow(9), { enableOnFormTags: false });

  // Hotkeys for navigation
  useHotkeys("left", () => goToPreviousDay(), { enableOnFormTags: false });
  useHotkeys("right", () => goToNextDay(), { enableOnFormTags: false });

  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-3">
        <HeaderTitle
          icon={<CalendarIcon width={20} height={20} />}
          text={`Calendar${visibleMonth && visibleYear ? ` - ${visibleMonth} ${visibleYear}` : ""}`}
        />

        <Select
          size="sm"
          selectedKeys={daysToShow ? [daysToShow.toString()] : ["1"]}
          onSelectionChange={(keys) => {
            const value = Array.from(keys)[0] as string;
            setDaysToShow(parseInt(value, 10));
          }}
          className="w-34"
          // className="max-w-fit min-w-24"
          classNames={{
            trigger: "bg-zinc-800 text-xs! cursor-pointer",
            value: "text-zinc-300",
          }}
          renderValue={(items) => {
            const item = items[0];
            const option = dayOptions.find((opt) => opt.value === item.key);
            return <span>{option?.label}</span>;
          }}
        >
          {dayOptions.map((option) => (
            <SelectItem
              key={option.value}
              aria-label={option.value}
              textValue={option.value}
              endContent={<Kbd keys={[]}>{option.kbd}</Kbd>}
            >
              {option.label}
            </SelectItem>
          ))}
        </Select>
      </div>

      <div className="relative flex items-center gap-2">
        <div className="flex items-center">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={goToPreviousDay}
          >
            <ArrowLeft01Icon className="h-5 w-5 text-zinc-400" />
          </Button>

          <Button isIconOnly size="sm" variant="light" onPress={goToNextDay}>
            <ArrowRight01Icon className="h-5 w-5 text-zinc-400" />
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
