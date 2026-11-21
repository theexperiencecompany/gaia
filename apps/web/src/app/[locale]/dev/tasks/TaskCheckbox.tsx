"use client";

import { Checkbox } from "@heroui/react";

import { checkboxVariants } from "@/components/shared/controlVariants";
import type { Priority } from "@/types/features/todoTypes";

/** The round tick a to-do and its subtasks lead with, ringed in the to-do's priority colour. */
export default function TaskCheckbox({
  label,
  isSelected,
  onChange,
  priority = "none",
  isSubtask = false,
  isReadOnly = false,
  className,
}: {
  label: string;
  isSelected: boolean;
  onChange: (isSelected: boolean) => void;
  priority?: Priority;
  isSubtask?: boolean;
  isReadOnly?: boolean;
  className?: string;
}) {
  return (
    <Checkbox
      aria-label={label}
      isSelected={isSelected}
      isReadOnly={isReadOnly}
      onChange={onChange}
      className={className}
    >
      <Checkbox.Content>
        <Checkbox.Control
          className={checkboxVariants({
            ring: priority,
            fill: isSubtask ? "muted" : "default",
            size: isSubtask ? "sm" : "md",
          })}
        >
          <Checkbox.Indicator />
        </Checkbox.Control>
      </Checkbox.Content>
    </Checkbox>
  );
}
