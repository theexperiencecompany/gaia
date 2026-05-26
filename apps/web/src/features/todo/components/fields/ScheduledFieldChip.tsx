"use client";

import { Button, Divider, Input } from "@heroui/react";
import { Cancel01Icon, Clock01Icon } from "@icons";
import BaseFieldChip from "./BaseFieldChip";

interface ScheduledFieldChipProps {
  value?: string; // ISO datetime string
  onChange: (scheduledAt?: string) => void;
  className?: string;
  timezone?: string; // User's preferred timezone
}

export default function ScheduledFieldChip({
  value,
  onChange,
  className,
  timezone,
}: Readonly<ScheduledFieldChipProps>) {
  // Use user's preferred timezone or fallback to browser timezone
  const userTimezone =
    timezone && timezone.trim() !== ""
      ? timezone
      : Intl.DateTimeFormat().resolvedOptions().timeZone;

  const formatDisplayValue = (dateString: string) => {
    const date = new Date(dateString);
    return new Intl.DateTimeFormat("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: userTimezone,
    }).format(date);
  };

  const displayValue = value ? formatDisplayValue(value) : undefined;

  // Extract date portion (YYYY-MM-DD) in the user's timezone
  const dateInputValue = value
    ? new Intl.DateTimeFormat("en-CA", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        timeZone: userTimezone,
      }).format(new Date(value))
    : "";

  // Extract time portion (HH:mm) in the user's timezone
  const timeInputValue = value
    ? new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: userTimezone,
      }).format(new Date(value))
    : "";

  const buildISOFromParts = (datePart: string, timePart: string): string => {
    if (timezone) {
      // Build an ISO string that represents this wall-clock time in the user's timezone
      // Use Intl to compute the offset, then adjust
      const naive = new Date(`${datePart}T${timePart}:00`);
      const utcStr = naive.toLocaleString("en-US", { timeZone: "UTC" });
      const tzStr = naive.toLocaleString("en-US", { timeZone: timezone });
      const utcDate = new Date(utcStr);
      const tzDate = new Date(tzStr);
      const offsetMs = utcDate.getTime() - tzDate.getTime();
      const adjusted = new Date(naive.getTime() + offsetMs);
      return adjusted.toISOString();
    }
    const [year, month, day] = datePart.split("-").map(Number);
    const [hour, minute] = timePart.split(":").map(Number);
    const date = new Date(year, month - 1, day, hour, minute);
    return date.toISOString();
  };

  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const datePart = e.target.value;
    if (!datePart) {
      onChange(undefined);
      return;
    }
    const time = timeInputValue || "09:00";
    onChange(buildISOFromParts(datePart, time));
  };

  const handleTimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const timePart = e.target.value;
    if (!timePart) return;
    const date = dateInputValue || new Date().toISOString().split("T")[0];
    onChange(buildISOFromParts(date, timePart));
  };

  const handleQuickSchedule = (hoursFromNow: number, onClose?: () => void) => {
    const date = new Date();
    date.setHours(date.getHours() + hoursFromNow);
    onChange(date.toISOString());
    onClose?.();
  };

  return (
    <BaseFieldChip
      label="Schedule"
      value={displayValue}
      placeholder="Schedule"
      icon={<Clock01Icon width={18} height={18} />}
      variant={value ? "primary" : "default"}
      className={className}
    >
      {({ onClose }) => (
        <div className="p-1">
          <div className="border-0 bg-zinc-900 p-3 flex flex-col gap-2">
            <Input
              type="date"
              value={dateInputValue}
              onChange={handleDateChange}
              size="sm"
              variant="flat"
              className="w-full"
              aria-label="Select scheduled date"
            />
            <Input
              type="time"
              value={timeInputValue}
              onChange={handleTimeChange}
              size="sm"
              variant="flat"
              className="w-full"
              aria-label="Select scheduled time"
            />
          </div>

          {/* Quick schedule options */}
          <Button
            variant="light"
            fullWidth
            radius="lg"
            className="justify-start gap-2 px-3 text-zinc-500"
            startContent={<Clock01Icon width={18} height={18} />}
            onPress={() => handleQuickSchedule(1, onClose)}
          >
            In 1 hour
          </Button>
          <Button
            variant="light"
            fullWidth
            radius="lg"
            className="justify-start gap-2 px-3 text-zinc-500"
            startContent={<Clock01Icon width={18} height={18} />}
            onPress={() => handleQuickSchedule(4, onClose)}
          >
            In 4 hours
          </Button>
          <Button
            variant="light"
            fullWidth
            radius="lg"
            className="justify-start gap-2 px-3 text-zinc-500"
            startContent={<Clock01Icon width={18} height={18} />}
            onPress={() => handleQuickSchedule(24, onClose)}
          >
            Tomorrow
          </Button>

          {/* Clear option */}
          {value && (
            <>
              <Divider className="my-1 bg-zinc-700" />
              <Button
                variant="light"
                fullWidth
                radius="lg"
                className="justify-start gap-2 px-3 text-red-400"
                startContent={<Cancel01Icon width={18} height={18} />}
                onPress={() => {
                  onChange(undefined);
                  onClose();
                }}
              >
                Clear schedule
              </Button>
            </>
          )}
        </div>
      )}
    </BaseFieldChip>
  );
}
