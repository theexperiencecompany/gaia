import { Input, Textarea } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { useEffect, useState } from "react";

import {
  buildCronExpression,
  type CronSchedule,
  parseCronExpression,
} from "../utils/cronUtils";

interface ScheduleBuilderProps {
  value?: string; // cron expression
  onChange: (cronExpression: string) => void;
  userTimezone?: string; // User's timezone for display only
}

interface SimpleSchedule {
  frequency: "every" | "once" | "custom";
  interval: "day" | "week" | "month";
  dayOfWeek: string;
  dayOfMonth: string;
  hour: string;
  minute: string;
}

// Pure function to initialize schedule state from cron expression
const initializeScheduleFromCron = (
  cronExpression?: string,
): SimpleSchedule => {
  const defaultSchedule: SimpleSchedule = {
    frequency: "every",
    interval: "day",
    dayOfWeek: "1",
    dayOfMonth: "1",
    hour: "9",
    minute: "0",
  };

  if (!cronExpression?.trim()) {
    return defaultSchedule;
  }

  const parsed = parseCronExpression(cronExpression);

  if (parsed.type === "custom") {
    return {
      ...defaultSchedule,
      frequency: "custom",
    };
  }

  return {
    frequency: "every",
    interval:
      parsed.type === "daily"
        ? "day"
        : parsed.type === "weekly"
          ? "week"
          : parsed.type === "monthly"
            ? "month"
            : "day",
    dayOfWeek: parsed.dayOfWeek?.toString() || "1",
    dayOfMonth: parsed.dayOfMonth?.toString() || "1",
    hour: parsed.hour?.toString() || "9",
    minute: parsed.minute?.toString() || "0",
  };
};

// Pure function to initialize custom cron state
const initializeCustomCron = (cronExpression?: string): string => {
  if (!cronExpression?.trim()) return "";

  const parsed = parseCronExpression(cronExpression);
  return parsed.type === "custom"
    ? parsed.customExpression || cronExpression
    : "";
};

// Helper to convert 24h to 12h for display
const to12Hour = (hour24: number): { hour12: number; ampm: "AM" | "PM" } => {
  if (hour24 === 0) return { hour12: 12, ampm: "AM" };
  if (hour24 === 12) return { hour12: 12, ampm: "PM" };
  if (hour24 < 12) return { hour12: hour24, ampm: "AM" };
  return { hour12: hour24 - 12, ampm: "PM" };
};

// Helper to convert 12h to 24h for storage
const to24Hour = (hour12: number, ampm: "AM" | "PM"): number => {
  if (ampm === "AM") return hour12 === 12 ? 0 : hour12;
  return hour12 === 12 ? 12 : hour12 + 12;
};

export const ScheduleBuilder = ({ value, onChange }: ScheduleBuilderProps) => {
  // Initialize state using pure functions - much faster and cleaner
  const [simpleSchedule, setSimpleSchedule] = useState<SimpleSchedule>(() =>
    initializeScheduleFromCron(value),
  );
  const [customCron, setCustomCron] = useState<string>(() =>
    initializeCustomCron(value),
  );

  // Update state when value prop changes (e.g., when switching between workflow cards)
  useEffect(() => {
    const newSimpleSchedule = initializeScheduleFromCron(value);
    const newCustomCron = initializeCustomCron(value);

    setSimpleSchedule(newSimpleSchedule);
    setCustomCron(newCustomCron);
  }, [value]);

  const handleSimpleScheduleChange = (updates: Partial<SimpleSchedule>) => {
    const newSchedule = { ...simpleSchedule, ...updates };
    setSimpleSchedule(newSchedule);

    // Only generate cron if not in custom mode
    if (newSchedule.frequency === "custom") return;

    // Convert to cron expression
    let cronSchedule: CronSchedule;
    switch (newSchedule.interval) {
      case "day":
        cronSchedule = {
          type: "daily",
          hour: parseInt(newSchedule.hour, 10),
          minute: parseInt(newSchedule.minute, 10),
        };
        break;
      case "week":
        cronSchedule = {
          type: "weekly",
          hour: parseInt(newSchedule.hour, 10),
          minute: parseInt(newSchedule.minute, 10),
          dayOfWeek: parseInt(newSchedule.dayOfWeek, 10),
        };
        break;
      case "month":
        cronSchedule = {
          type: "monthly",
          hour: parseInt(newSchedule.hour, 10),
          minute: parseInt(newSchedule.minute, 10),
          dayOfMonth: parseInt(newSchedule.dayOfMonth, 10),
        };
        break;
      default:
        cronSchedule = {
          type: "daily",
          hour: parseInt(newSchedule.hour, 10),
          minute: parseInt(newSchedule.minute, 10),
        };
    }

    const cronExpr = buildCronExpression(cronSchedule);
    onChange(cronExpr);
  };

  const handleCustomCronChange = (cron: string) => {
    setCustomCron(cron);
    onChange(cron);
  };

  // Get 12-hour display values from 24-hour stored value
  const hour24 = parseInt(simpleSchedule.hour, 10) || 0;
  const { hour12, ampm } = to12Hour(hour24);

  // Handle 12-hour time changes
  const handleHour12Change = (newHour12: string) => {
    const h12 = parseInt(newHour12, 10) || 1;
    const h24 = to24Hour(h12, ampm);
    handleSimpleScheduleChange({ hour: h24.toString() });
  };

  const handleAmpmChange = (newAmpm: "AM" | "PM") => {
    const h24 = to24Hour(hour12, newAmpm);
    handleSimpleScheduleChange({ hour: h24.toString() });
  };

  return (
    <div className="w-full">
      {/* Natural Language Schedule Builder */}
      <div className="flex w-full flex-row items-center gap-3 text-sm">
        <span>Run</span>

        <Select
          aria-label="Select every or once or custom"
          size="sm"
          selectedKeys={new Set([simpleSchedule.frequency])}
          onSelectionChange={(keys) =>
            handleSimpleScheduleChange({
              frequency: Array.from(keys)[0] as SimpleSchedule["frequency"],
            })
          }
          className="min-w-26"
        >
          <SelectItem key="every" textValue="Every">
            Every
          </SelectItem>
          <SelectItem key="once" textValue="Once">
            Once
          </SelectItem>
          <SelectItem key="custom" textValue="Custom">
            Custom
          </SelectItem>
        </Select>

        {simpleSchedule.frequency !== "custom" && (
          <>
            <Select
              size="sm"
              aria-label="Select day or week or month"
              selectedKeys={new Set([simpleSchedule.interval])}
              onSelectionChange={(keys) =>
                handleSimpleScheduleChange({
                  interval: Array.from(keys)[0] as SimpleSchedule["interval"],
                })
              }
              className="min-w-26"
            >
              <SelectItem key="day" textValue="Day">
                Day
              </SelectItem>
              <SelectItem key="week" textValue="Week">
                Week
              </SelectItem>
              <SelectItem key="month" textValue="Month">
                Month
              </SelectItem>
            </Select>

            {simpleSchedule.interval === "week" && (
              <>
                <span>on</span>
                <Select
                  size="sm"
                  selectedKeys={new Set([simpleSchedule.dayOfWeek])}
                  onSelectionChange={(keys) =>
                    handleSimpleScheduleChange({
                      dayOfWeek: Array.from(keys)[0] as string,
                    })
                  }
                  className="min-w-32"
                >
                  <SelectItem key="1" textValue="Monday">
                    Monday
                  </SelectItem>
                  <SelectItem key="2" textValue="Tuesday">
                    Tuesday
                  </SelectItem>
                  <SelectItem key="3" textValue="Wednesday">
                    Wednesday
                  </SelectItem>
                  <SelectItem key="4" textValue="Thursday">
                    Thursday
                  </SelectItem>
                  <SelectItem key="5" textValue="Friday">
                    Friday
                  </SelectItem>
                  <SelectItem key="6" textValue="Saturday">
                    Saturday
                  </SelectItem>
                  <SelectItem key="0" textValue="Sunday">
                    Sunday
                  </SelectItem>
                </Select>
              </>
            )}

            {simpleSchedule.interval === "month" && (
              <>
                <span className="text-nowrap">on the</span>
                <Select
                  aria-label="Select day of the month"
                  size="sm"
                  selectionMode="single"
                  selectedKeys={new Set([simpleSchedule.dayOfMonth])}
                  onSelectionChange={(keys) => {
                    const selectedDay = Array.from(keys)[0] as string;
                    console.log("Monthly day selected:", selectedDay);
                    handleSimpleScheduleChange({
                      dayOfMonth: selectedDay,
                    });
                  }}
                  className="min-w-20"
                  placeholder="Day"
                >
                  {Array.from({ length: 31 }, (_, i) => (
                    <SelectItem
                      key={(i + 1).toString()}
                      textValue={(i + 1).toString()}
                    >
                      {i + 1}
                    </SelectItem>
                  ))}
                </Select>
              </>
            )}

            <span>at</span>
            <div className="flex items-center gap-1">
              <Input
                size="sm"
                type="number"
                min="1"
                max="12"
                value={hour12.toString()}
                onChange={(e) => handleHour12Change(e.target.value)}
                className="w-16"
              />
              <span>:</span>
              <Input
                size="sm"
                type="number"
                min="0"
                max="59"
                value={simpleSchedule.minute}
                onChange={(e) =>
                  handleSimpleScheduleChange({ minute: e.target.value })
                }
                className="w-16"
              />
              <Select
                aria-label="Select AM or PM"
                size="sm"
                selectedKeys={new Set([ampm])}
                onSelectionChange={(keys) =>
                  handleAmpmChange(Array.from(keys)[0] as "AM" | "PM")
                }
                className="w-22"
              >
                <SelectItem key="AM" textValue="AM">
                  AM
                </SelectItem>
                <SelectItem key="PM" textValue="PM">
                  PM
                </SelectItem>
              </Select>
            </div>
          </>
        )}
      </div>

      {simpleSchedule.frequency === "custom" && (
        <div className="mt-4 w-full">
          <Textarea
            placeholder="0 9 * * *"
            description="Format: minute hour day-of-month month day-of-week"
            value={customCron}
            label="Cron Job"
            fullWidth
            onChange={(e) => handleCustomCronChange(e.target.value)}
          />
        </div>
      )}
    </div>
  );
};
