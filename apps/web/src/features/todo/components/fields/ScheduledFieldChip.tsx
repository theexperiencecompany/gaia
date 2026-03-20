"use client";

import { Input } from "@heroui/react";
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
}: ScheduledFieldChipProps) {
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
            <input
              type="time"
              value={timeInputValue}
              onChange={handleTimeChange}
              className="w-full rounded-lg bg-zinc-800 px-3 py-2 text-sm text-zinc-200 outline-none focus:ring-1 focus:ring-zinc-600"
              aria-label="Select scheduled time"
            />
          </div>

          {/* Quick schedule options */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleQuickSchedule(1, onClose);
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-zinc-500 transition-colors hover:bg-zinc-800"
          >
            <Clock01Icon width={18} height={18} />
            In 1 hour
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleQuickSchedule(4, onClose);
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-zinc-500 transition-colors hover:bg-zinc-800"
          >
            <Clock01Icon width={18} height={18} />
            In 4 hours
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleQuickSchedule(24, onClose);
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-zinc-500 transition-colors hover:bg-zinc-800"
          >
            <Clock01Icon width={18} height={18} />
            Tomorrow
          </button>

          {/* Clear option */}
          {value && (
            <>
              <div className="my-1 h-px bg-zinc-700" />
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onChange(undefined);
                  onClose();
                }}
                className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-red-400 transition-colors hover:bg-zinc-800"
              >
                <Cancel01Icon width={18} height={18} />
                Clear schedule
              </button>
            </>
          )}
        </div>
      )}
    </BaseFieldChip>
  );
}
