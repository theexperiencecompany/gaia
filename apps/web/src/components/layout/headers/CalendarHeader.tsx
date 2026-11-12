"use client";

import { Button, Kbd, ListBox, Select } from "@heroui/react";
import {
  ArrowLeft01Icon,
  ArrowRight01Icon,
  CalendarAdd01Icon,
  CalendarIcon,
} from "@icons";
import { useHotkeys } from "react-hotkeys-hook";
import { SidebarHeaderButton } from "@/components/layout/headers/SidebarHeaderButton";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
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
          selectedKey={daysToShow ? daysToShow.toString() : "1"}
          onSelectionChange={(key) => {
            if (key != null) {
              setDaysToShow(parseInt(String(key), 10));
            }
          }}
          className="w-34"
        >
          <Select.Trigger className="bg-zinc-800 text-xs! cursor-pointer">
            <GaiaSelectValue>
              {
                dayOptions.find(
                  (opt) =>
                    opt.value === (daysToShow ? daysToShow.toString() : "1"),
                )?.label
              }
            </GaiaSelectValue>
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {dayOptions.map((option) => (
                <ListBox.Item
                  key={option.value}
                  id={option.value}
                  textValue={option.label}
                  className="flex items-center justify-between"
                >
                  {option.label}
                  <Kbd>{option.kbd}</Kbd>
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      </div>

      <div className="relative flex items-center gap-2">
        <div className="flex items-center">
          <Button
            isIconOnly
            size="sm"
            variant="ghost"
            onPress={goToPreviousDay}
          >
            <ArrowLeft01Icon className="h-5 w-5 text-zinc-400" />
          </Button>

          <Button isIconOnly size="sm" variant="ghost" onPress={goToNextDay}>
            <ArrowRight01Icon className="h-5 w-5 text-zinc-400" />
          </Button>
          <GaiaButton
            variant="default-soft"
            onPress={goToToday}
            size="sm"
            className="ml-"
          >
            Today
          </GaiaButton>
        </div>

        {createEventAction && (
          <SidebarHeaderButton
            aria-label="Create new calendar event"
            tooltip="Create new calendar event"
            onClick={createEventAction}
          >
            <CalendarAdd01Icon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-colors group-hover:text-primary" />
          </SidebarHeaderButton>
        )}
      </div>
    </div>
  );
}
