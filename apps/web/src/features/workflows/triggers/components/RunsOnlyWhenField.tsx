"use client";

import { Textarea } from "@heroui/input";
import { Switch } from "@heroui/switch";
import {
  GATE_CONDITION_MAX_CHARS,
  GATE_CONDITION_PLACEHOLDER,
  GATE_OFF_NOTE,
  GATE_SHADOW_NOTE,
  GATE_SWITCH_LABEL,
  RUNS_ONLY_WHEN_LABEL,
} from "../../constants/gates";

interface RunsOnlyWhenFieldProps {
  /** The condition the user reads; a system gate's is its preset's wording. */
  condition: string;
  enabled: boolean;
  /** False for a system gate: GAIA owns its wording, so it can only be switched. */
  editable: boolean;
  /** Whether the gate may skip a run yet; unknown until a new condition is saved. */
  enforced?: boolean;
  onConditionChange: (condition: string) => void;
  onEnabledChange: (enabled: boolean) => void;
  onConditionBlur?: () => void;
  isDisabled?: boolean;
}

/** A gate's "Runs only when" row: its condition, an on/off switch, and what it does today. */
export function RunsOnlyWhenField({
  condition,
  enabled,
  editable,
  enforced,
  onConditionChange,
  onEnabledChange,
  onConditionBlur,
  isDisabled = false,
}: RunsOnlyWhenFieldProps) {
  const hasCondition = condition.trim() !== "";
  let note: string | null = null;
  if (hasCondition && !enabled) note = GATE_OFF_NOTE;
  else if (hasCondition && enforced === false) note = GATE_SHADOW_NOTE;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-zinc-200">
          {RUNS_ONLY_WHEN_LABEL}
        </span>
        {hasCondition && (
          <Switch
            size="sm"
            isSelected={enabled}
            onValueChange={onEnabledChange}
            isDisabled={isDisabled}
            aria-label={GATE_SWITCH_LABEL}
          />
        )}
      </div>
      {editable ? (
        <Textarea
          aria-label={RUNS_ONLY_WHEN_LABEL}
          value={condition}
          onValueChange={onConditionChange}
          onBlur={onConditionBlur}
          placeholder={GATE_CONDITION_PLACEHOLDER}
          maxLength={GATE_CONDITION_MAX_CHARS}
          minRows={1}
          maxRows={4}
          variant="flat"
          isDisabled={isDisabled}
        />
      ) : (
        <p className="text-sm leading-relaxed text-zinc-400">{condition}</p>
      )}
      {note && <p className="text-xs text-zinc-500">{note}</p>}
    </div>
  );
}
