"use client";

import { CheckmarkCircle02Icon } from "@icons";
import { FIRST_STEP_DEFINITIONS } from "@/features/first-steps/constants";
import { cn } from "@/lib/utils";
import type { FirstStepStatus } from "@/types/features/firstStepsTypes";

interface FirstStepRowProps {
  step: FirstStepStatus;
  onActivate: (step: FirstStepStatus) => void;
  /** Row surface. The dashboard card needs the chip the other cards use; the
   * floating panel is already a raised surface and stays flat. */
  className?: string;
}

/**
 * One activation step. A button, not a checkbox: `done` is derived server-side
 * and the click runs the step's action, so anything toggleable would be lying
 * about what the control does — and would need its own toggle suppressed.
 *
 * A done step keeps its action rather than going inert, because re-running it
 * (connect a second integration, write another workflow) is the point.
 */
export function FirstStepRow({
  step,
  onActivate,
  className,
}: FirstStepRowProps) {
  const {
    label,
    description,
    icon: StepIcon,
  } = FIRST_STEP_DEFINITIONS[step.key];
  // The step's own icon while it is open, a tick once it is done: two glyphs on
  // one line read as noise, and the tick is the only news on a finished row.
  const Icon = step.done ? CheckmarkCircle02Icon : StepIcon;

  return (
    <button
      type="button"
      onClick={() => onActivate(step)}
      className={cn(
        "flex w-full min-w-0 cursor-pointer items-start gap-2.5 rounded-2xl px-2 py-1.5 text-left transition-colors duration-200 hover:bg-white/5 focus-visible:bg-white/5 focus-visible:outline-none active:scale-[0.99]",
        className,
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 size-4 shrink-0",
          step.done ? "text-success" : "text-zinc-400",
        )}
      />
      <span className="flex min-w-0 flex-col">
        <span
          className={cn(
            "truncate text-sm font-medium",
            step.done ? "text-zinc-400" : "text-zinc-200",
          )}
        >
          {label}
        </span>
        <span className="truncate text-xs text-zinc-500">{description}</span>
      </span>
    </button>
  );
}
