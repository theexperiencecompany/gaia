"use client";

import { Flag } from "@/icons";
import { Priority } from "@/types/features/todoTypes";

import BaseFieldChip from "./BaseFieldChip";

interface PriorityFieldChipProps {
  value?: Priority;
  onChange: (priority: Priority) => void;
  className?: string;
}

const priorityOptions = [
  { value: Priority.NONE, label: "None", color: "default" as const },
  { value: Priority.LOW, label: "Low", color: "primary" as const },
  { value: Priority.MEDIUM, label: "Medium", color: "warning" as const },
  { value: Priority.HIGH, label: "High", color: "danger" as const },
];

export default function PriorityFieldChip({
  value = Priority.NONE,
  onChange,
  className,
}: PriorityFieldChipProps) {
  const selectedOption = priorityOptions.find(
    (option) => option.value === value,
  );
  const displayValue =
    value === Priority.NONE ? undefined : selectedOption?.label;
  const variant = selectedOption?.color || "default";

  return (
    <BaseFieldChip
      label="Priority"
      value={displayValue}
      placeholder="Priority"
      icon={<Flag size={14} />}
      variant={variant}
      className={className}
    >
      {({ onClose }) => (
        <div className="p-1">
          {priorityOptions.map((option) => {
            const shortcut =
              option.value === Priority.HIGH
                ? "P1"
                : option.value === Priority.MEDIUM
                  ? "P2"
                  : option.value === Priority.LOW
                    ? "P3"
                    : null;

            return (
              <div
                key={option.value}
                onClick={() => {
                  onChange(option.value);
                  onClose();
                }}
                className="flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-zinc-300 transition-colors hover:bg-zinc-800"
              >
                <div className="flex items-center gap-2">
                  <Flag
                    size={14}
                    className={
                      option.value === Priority.HIGH
                        ? "text-red-400"
                        : option.value === Priority.MEDIUM
                          ? "text-yellow-400"
                          : option.value === Priority.LOW
                            ? "text-blue-400"
                            : "text-zinc-500"
                    }
                  />
                  <span>{option.label}</span>
                </div>
                {shortcut && (
                  <span className="font-mono text-xs text-zinc-500">
                    {shortcut}
                  </span>
                )}
              </div>
            );
          })}

          {/* Hint */}
          <div className="mt-1 px-3 py-2">
            <p className="text-xs text-zinc-500">
              Type{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">p1</span>,{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">p2</span>, or{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">p3</span> in
              title/description
            </p>
          </div>
        </div>
      )}
    </BaseFieldChip>
  );
}
