"use client";

import { Cancel01Icon, RepeatIcon } from "@icons";

import BaseFieldChip from "./BaseFieldChip";

interface RecurrenceFieldChipProps {
  value?: string;
  onChange: (value: string | undefined) => void;
  className?: string;
}

const RECURRENCE_OPTIONS: { label: string; value: string | undefined }[] = [
  { label: "No recurrence", value: undefined },
  { label: "Daily", value: "daily" },
  { label: "Weekly", value: "weekly" },
  { label: "Every 4 hours", value: "every_4h" },
];

const RECURRENCE_LABELS: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  every_4h: "Every 4 hours",
};

export default function RecurrenceFieldChip({
  value,
  onChange,
  className,
}: RecurrenceFieldChipProps) {
  const displayValue = value ? (RECURRENCE_LABELS[value] ?? value) : undefined;

  return (
    <BaseFieldChip
      label="Recurrence"
      value={displayValue}
      placeholder="No recurrence"
      icon={<RepeatIcon width={18} height={18} />}
      variant={value ? "secondary" : "default"}
      className={className}
    >
      {({ onClose }) => (
        <div className="p-1">
          {RECURRENCE_OPTIONS.map((option) => (
            <div
              key={option.value ?? "none"}
              onClick={(e) => {
                e.stopPropagation();
                onChange(option.value);
                onClose();
              }}
              className={`flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-zinc-800 ${
                value === option.value || (!value && option.value === undefined)
                  ? "text-zinc-200"
                  : "text-zinc-500"
              }`}
            >
              {option.value === undefined ? (
                <Cancel01Icon width={18} height={18} />
              ) : (
                <RepeatIcon width={18} height={18} />
              )}
              {option.label}
            </div>
          ))}
        </div>
      )}
    </BaseFieldChip>
  );
}
