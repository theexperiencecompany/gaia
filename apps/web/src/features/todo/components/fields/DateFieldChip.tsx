"use client";

import { Input } from "@heroui/react";
import { CalendarIcon, Cancel01Icon } from "@icons";
import { format, isToday, isTomorrow, isYesterday } from "date-fns";

import { getBrowserTimezone } from "@/lib/timezone";
import BaseFieldChip from "./BaseFieldChip";
import FieldChipOption from "./FieldChipOption";

interface DateFieldChipProps {
  value?: string; // ISO date string
  onChange: (date?: string, timezone?: string) => void;
  className?: string;
  timezone?: string; // User's preferred timezone
}

const formatDisplayDate = (dateString: string) => {
  const date = new Date(dateString);

  if (isToday(date)) return "Today";
  if (isTomorrow(date)) return "Tomorrow";
  if (isYesterday(date)) return "Yesterday";

  return format(date, "MMM d");
};

export default function DateFieldChip({
  value,
  onChange,
  className,
  timezone,
}: DateFieldChipProps) {
  // Use user's preferred timezone or fallback to browser timezone
  // Handle empty string as "auto-detect"
  const userTimezone =
    timezone && timezone.trim() !== "" ? timezone : getBrowserTimezone();
  const displayValue = value ? formatDisplayDate(value) : undefined;

  const handleDateInputChange = (
    e: React.ChangeEvent<HTMLInputElement>,
    onClose?: () => void,
  ) => {
    const inputValue = e.target.value;
    if (inputValue) {
      const date = new Date(inputValue);
      onChange(date.toISOString(), userTimezone);
      onClose?.();
    } else {
      onChange(undefined, undefined);
      onClose?.();
    }
  };

  const handleQuickDate = (days: number, onClose?: () => void) => {
    const date = new Date();
    date.setDate(date.getDate() + days);
    onChange(date.toISOString(), userTimezone);
    onClose?.();
  };

  return (
    <BaseFieldChip
      label="Due Date"
      value={displayValue}
      placeholder="Due date"
      icon={<CalendarIcon width={18} height={18} />}
      variant={value ? "success" : "default"}
      className={className}
    >
      {({ onClose }) => (
        <div className="p-1">
          <div className="border-0 bg-zinc-900 p-3">
            <Input
              type="date"
              value={value ? value.split("T")[0] : ""}
              onChange={(e) => handleDateInputChange(e, onClose)}
              size="sm"
              variant="flat"
              className="w-full"
              aria-label="Select due date"
            />
          </div>

          {/* Quick date options */}
          <FieldChipOption
            onSelect={() => handleQuickDate(0, onClose)}
            className="gap-2 rounded-lg text-zinc-500"
          >
            <CalendarIcon width={18} height={18} />
            Today
          </FieldChipOption>
          <FieldChipOption
            onSelect={() => handleQuickDate(1, onClose)}
            className="gap-2 rounded-lg text-zinc-500"
          >
            <CalendarIcon width={18} height={18} />
            Tomorrow
          </FieldChipOption>
          <FieldChipOption
            onSelect={() => handleQuickDate(3, onClose)}
            className="gap-2 rounded-lg text-zinc-500"
          >
            <CalendarIcon width={18} height={18} />
            In 3 days
          </FieldChipOption>
          <FieldChipOption
            onSelect={() => handleQuickDate(7, onClose)}
            className="gap-2 rounded-lg text-zinc-500"
          >
            <CalendarIcon width={18} height={18} />
            Next week
          </FieldChipOption>

          {/* Clear date option */}
          {value && (
            <>
              <div className="my-1 h-px bg-zinc-700" />
              <FieldChipOption
                onSelect={() => {
                  onChange(undefined, undefined);
                  onClose();
                }}
                className="gap-2 rounded-lg text-red-400"
              >
                <Cancel01Icon width={18} height={18} />
                Clear date
              </FieldChipOption>
            </>
          )}

          {/* Hint */}
          <div className="mt-1 px-3 py-2">
            <p className="text-xs text-zinc-500">
              Type{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">today</span>,{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">
                tomorrow
              </span>
              , or{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">
                in 3 days
              </span>{" "}
              in title/description
            </p>
          </div>
        </div>
      )}
    </BaseFieldChip>
  );
}
