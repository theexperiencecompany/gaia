"use client";

import { Button } from "@heroui/react";
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
}: Readonly<RecurrenceFieldChipProps>) {
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
          {RECURRENCE_OPTIONS.map((option) => {
            const isOptionSelected =
              value === option.value || (!value && option.value === undefined);
            return (
              <Button
                key={option.value ?? "none"}
                variant="light"
                fullWidth
                radius="lg"
                aria-pressed={isOptionSelected}
                className={`justify-start gap-2 px-3 text-sm ${
                  isOptionSelected ? "text-zinc-200" : "text-zinc-500"
                }`}
                startContent={
                  option.value === undefined ? (
                    <Cancel01Icon width={18} height={18} />
                  ) : (
                    <RepeatIcon width={18} height={18} />
                  )
                }
                onPress={() => {
                  onChange(option.value);
                  onClose();
                }}
              >
                {option.label}
              </Button>
            );
          })}
        </div>
      )}
    </BaseFieldChip>
  );
}
