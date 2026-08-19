import { Input } from "@heroui/input";
import { Select, SelectItem } from "@heroui/select";
import { Clock01Icon, InformationCircleIcon } from "@icons";
import { useEffect, useMemo, useState } from "react";

import { getTimezoneList, normalizeTimezone } from "@/utils/timezoneUtils";
import {
  buildCronExpression,
  type CronSchedule,
  describeCron,
  parseCronExpression,
} from "../utils/cronUtils";
import { TimezoneAutocomplete } from "./TimezoneAutocomplete";

interface ScheduleBuilderProps {
  value?: string;
  onChange: (cronExpression: string) => void;
  timezone: string;
  onTimezoneChange: (timezone: string) => void;
}

interface SimpleSchedule {
  frequency: "every" | "once" | "custom";
  interval: "day" | "week" | "month";
  dayOfWeek: string;
  dayOfMonth: string;
  hour: string;
  minute: string;
}

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

const initializeCustomCron = (cronExpression?: string): string => {
  if (!cronExpression?.trim()) return "";
  const parsed = parseCronExpression(cronExpression);
  return parsed.type === "custom"
    ? parsed.customExpression || cronExpression
    : "";
};

const SELECT_CLASSNAMES = { popoverContent: "min-w-fit" } as const;

const to12Hour = (hour24: number): { hour12: number; ampm: "AM" | "PM" } => {
  if (hour24 === 0) return { hour12: 12, ampm: "AM" };
  if (hour24 === 12) return { hour12: 12, ampm: "PM" };
  if (hour24 < 12) return { hour12: hour24, ampm: "AM" };
  return { hour12: hour24 - 12, ampm: "PM" };
};

const to24Hour = (hour12: number, ampm: "AM" | "PM"): number => {
  if (ampm === "AM") return hour12 === 12 ? 0 : hour12;
  return hour12 === 12 ? 12 : hour12 + 12;
};

interface ScheduleFrequencySelectorProps {
  frequency: SimpleSchedule["frequency"];
  onChange: (frequency: SimpleSchedule["frequency"]) => void;
}

function ScheduleFrequencySelector({
  frequency,
  onChange,
}: ScheduleFrequencySelectorProps) {
  return (
    <Select
      aria-label="Select every or once or custom"
      size="sm"
      selectedKeys={new Set([frequency])}
      onSelectionChange={(keys) =>
        onChange(Array.from(keys)[0] as SimpleSchedule["frequency"])
      }
      className="w-20 shrink-0"
      classNames={SELECT_CLASSNAMES}
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
  );
}

interface ScheduleTimeInputsProps {
  hour12: number;
  minute: string;
  ampm: "AM" | "PM";
  onHour12Change: (value: string) => void;
  onMinuteChange: (value: string) => void;
  onAmpmChange: (value: "AM" | "PM") => void;
}

function ScheduleTimeInputs({
  hour12,
  minute,
  ampm,
  onHour12Change,
  onMinuteChange,
  onAmpmChange,
}: ScheduleTimeInputsProps) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      <Input
        size="sm"
        type="number"
        min="1"
        max="12"
        value={hour12.toString()}
        onChange={(e) => onHour12Change(e.target.value)}
        className="w-12"
      />
      <span className="text-zinc-500">:</span>
      <Input
        size="sm"
        type="number"
        min="0"
        max="59"
        value={minute.padStart(2, "0")}
        onChange={(e) => onMinuteChange(e.target.value)}
        className="w-12"
      />
      <Select
        aria-label="Select AM or PM"
        size="sm"
        selectedKeys={new Set([ampm])}
        onSelectionChange={(keys) =>
          onAmpmChange(Array.from(keys)[0] as "AM" | "PM")
        }
        className="w-17"
        classNames={SELECT_CLASSNAMES}
      >
        <SelectItem key="AM" textValue="AM">
          AM
        </SelectItem>
        <SelectItem key="PM" textValue="PM">
          PM
        </SelectItem>
      </Select>
    </div>
  );
}

interface ScheduleIntervalFieldsProps {
  interval: SimpleSchedule["interval"];
  dayOfWeek: string;
  dayOfMonth: string;
  onIntervalChange: (interval: SimpleSchedule["interval"]) => void;
  onDayOfWeekChange: (day: string) => void;
  onDayOfMonthChange: (day: string) => void;
}

function ScheduleIntervalFields({
  interval,
  dayOfWeek,
  dayOfMonth,
  onIntervalChange,
  onDayOfWeekChange,
  onDayOfMonthChange,
}: ScheduleIntervalFieldsProps) {
  return (
    <>
      <Select
        size="sm"
        aria-label="Select day or week or month"
        selectedKeys={new Set([interval])}
        onSelectionChange={(keys) =>
          onIntervalChange(Array.from(keys)[0] as SimpleSchedule["interval"])
        }
        className="w-20 shrink-0"
        classNames={SELECT_CLASSNAMES}
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
      {interval === "week" && (
        <>
          <span className="shrink-0 text-zinc-400">on</span>
          <Select
            size="sm"
            selectedKeys={new Set([dayOfWeek])}
            onSelectionChange={(keys) =>
              onDayOfWeekChange(Array.from(keys)[0] as string)
            }
            className="w-22 shrink-0"
            classNames={SELECT_CLASSNAMES}
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
      {interval === "month" && (
        <>
          <span className="shrink-0 text-nowrap text-zinc-400">on the</span>
          <Select
            aria-label="Select day of the month"
            size="sm"
            selectionMode="single"
            selectedKeys={new Set([dayOfMonth])}
            onSelectionChange={(keys) => {
              const selectedDay = Array.from(keys)[0] as string;
              onDayOfMonthChange(selectedDay);
            }}
            className="w-16 shrink-0"
            classNames={SELECT_CLASSNAMES}
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
    </>
  );
}

interface ScheduleSimpleSectionProps {
  simpleSchedule: SimpleSchedule;
  hour12: number;
  ampm: "AM" | "PM";
  timezone: string;
  timezoneOptions: { value: string; label: string; offset: string }[];
  onSimpleChange: (updates: Partial<SimpleSchedule>) => void;
  onHour12Change: (value: string) => void;
  onAmpmChange: (value: "AM" | "PM") => void;
  onTimezoneChange: (timezone: string) => void;
}

function ScheduleSimpleSection({
  simpleSchedule,
  hour12,
  ampm,
  timezone,
  timezoneOptions,
  onSimpleChange,
  onHour12Change,
  onAmpmChange,
  onTimezoneChange,
}: ScheduleSimpleSectionProps) {
  return (
    <>
      <ScheduleIntervalFields
        interval={simpleSchedule.interval}
        dayOfWeek={simpleSchedule.dayOfWeek}
        dayOfMonth={simpleSchedule.dayOfMonth}
        onIntervalChange={(interval) => onSimpleChange({ interval })}
        onDayOfWeekChange={(dayOfWeek) => onSimpleChange({ dayOfWeek })}
        onDayOfMonthChange={(dayOfMonth) => onSimpleChange({ dayOfMonth })}
      />
      <span className="shrink-0 text-zinc-400">at</span>
      <ScheduleTimeInputs
        hour12={hour12}
        minute={simpleSchedule.minute}
        ampm={ampm}
        onHour12Change={onHour12Change}
        onMinuteChange={(minute) => onSimpleChange({ minute })}
        onAmpmChange={onAmpmChange}
      />
      <span className="shrink-0 text-zinc-500">in</span>
      <div className="flex-1 min-w-18">
        <TimezoneAutocomplete
          timezone={timezone}
          options={timezoneOptions}
          onChange={onTimezoneChange}
          className="w-full"
        />
      </div>
    </>
  );
}

interface ScheduleCustomSectionProps {
  customCron: string;
  timezone: string;
  timezoneOptions: { value: string; label: string; offset: string }[];
  isInvalid: boolean;
  onCronChange: (cron: string) => void;
  onTimezoneChange: (timezone: string) => void;
}

function ScheduleCustomSection({
  customCron,
  timezone,
  timezoneOptions,
  isInvalid,
  onCronChange,
  onTimezoneChange,
}: ScheduleCustomSectionProps) {
  return (
    <>
      <Input
        placeholder="0 9 * * *"
        aria-label="Cron expression"
        value={customCron}
        size="sm"
        isInvalid={isInvalid}
        onChange={(e) => onCronChange(e.target.value)}
        className="w-40 shrink-0"
      />
      <span className="shrink-0 text-nowrap text-zinc-500">in</span>
      <div className="flex-1 min-w-18">
        <TimezoneAutocomplete
          timezone={timezone}
          options={timezoneOptions}
          onChange={onTimezoneChange}
          className="w-full"
        />
      </div>
    </>
  );
}

interface ScheduleCronPreviewProps {
  description?: string;
  isInvalid: boolean;
}

function ScheduleCronPreview({
  description,
  isInvalid,
}: ScheduleCronPreviewProps) {
  return (
    <div className="mt-2 flex items-center gap-1.5 text-xs">
      {description && !isInvalid ? (
        <>
          <Clock01Icon className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
          <span className="text-zinc-400">{description}</span>
        </>
      ) : (
        <>
          <InformationCircleIcon
            className={`h-3.5 w-3.5 shrink-0 ${
              isInvalid ? "text-danger" : "text-zinc-500"
            }`}
          />
          <span className={isInvalid ? "text-danger" : "text-zinc-500"}>
            minute hour day-of-month month day-of-week
          </span>
        </>
      )}
    </div>
  );
}

export const ScheduleBuilder = ({
  value,
  onChange,
  timezone,
  onTimezoneChange,
}: ScheduleBuilderProps) => {
  const [simpleSchedule, setSimpleSchedule] = useState<SimpleSchedule>(() =>
    initializeScheduleFromCron(value),
  );
  const [customCron, setCustomCron] = useState<string>(() =>
    initializeCustomCron(value),
  );
  const normalizedTimezone = normalizeTimezone(timezone);
  const timezoneOptions = useMemo(() => {
    const options = getTimezoneList(true).map((tz) => ({
      value: tz.value,
      label: tz.label,
      offset: tz.offset,
    }));
    if (
      normalizedTimezone &&
      !options.some((tz: { value: string }) => tz.value === normalizedTimezone)
    ) {
      options.unshift({
        value: normalizedTimezone,
        label: normalizedTimezone,
        offset: "",
      });
    }
    return options;
  }, [normalizedTimezone]);
  useEffect(() => {
    const newSimpleSchedule = initializeScheduleFromCron(value);
    const newCustomCron = initializeCustomCron(value);
    setSimpleSchedule(newSimpleSchedule);
    setCustomCron(newCustomCron);
  }, [value]);
  const handleSimpleScheduleChange = (updates: Partial<SimpleSchedule>) => {
    const newSchedule = { ...simpleSchedule, ...updates };
    setSimpleSchedule(newSchedule);
    if (newSchedule.frequency === "custom") return;
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
  const cronPreview = useMemo(() => describeCron(customCron), [customCron]);
  const showCronError = customCron.trim().length > 0 && !cronPreview.isValid;
  const hour24 = parseInt(simpleSchedule.hour, 10) || 0;
  const { hour12, ampm } = to12Hour(hour24);
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
      <div className="flex w-full flex-row items-center gap-x-2 text-sm">
        <span className="shrink-0 text-zinc-400">Run</span>
        <ScheduleFrequencySelector
          frequency={simpleSchedule.frequency}
          onChange={(frequency) => handleSimpleScheduleChange({ frequency })}
        />
        {simpleSchedule.frequency !== "custom" ? (
          <ScheduleSimpleSection
            simpleSchedule={simpleSchedule}
            hour12={hour12}
            ampm={ampm}
            timezone={normalizedTimezone}
            timezoneOptions={timezoneOptions}
            onSimpleChange={handleSimpleScheduleChange}
            onHour12Change={handleHour12Change}
            onAmpmChange={handleAmpmChange}
            onTimezoneChange={onTimezoneChange}
          />
        ) : (
          <ScheduleCustomSection
            customCron={customCron}
            timezone={normalizedTimezone}
            timezoneOptions={timezoneOptions}
            isInvalid={showCronError}
            onCronChange={handleCustomCronChange}
            onTimezoneChange={onTimezoneChange}
          />
        )}
      </div>
      {simpleSchedule.frequency === "custom" && (
        <ScheduleCronPreview
          description={cronPreview.description}
          isInvalid={showCronError}
        />
      )}
    </div>
  );
};
