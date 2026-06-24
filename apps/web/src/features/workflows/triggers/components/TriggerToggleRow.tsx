/**
 * A boolean setting row for the trigger settings card: label (+ optional hint)
 * on the left, a Switch on the right.
 */

"use client";

import { Switch } from "@heroui/switch";

interface TriggerToggleRowProps {
  label: string;
  hint?: string;
  isSelected: boolean;
  onValueChange: (value: boolean) => void;
}

export function TriggerToggleRow({
  label,
  hint,
  isSelected,
  onValueChange,
}: TriggerToggleRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3.5">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm font-medium text-zinc-200">{label}</span>
        {hint ? <span className="text-xs text-zinc-500">{hint}</span> : null}
      </div>
      <Switch
        size="sm"
        isSelected={isSelected}
        onValueChange={onValueChange}
        aria-label={label}
      />
    </div>
  );
}
