"use client";

import { Rocket01Icon } from "@icons";
import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { FirstStepRow } from "@/features/first-steps/components/FirstStepRow";
import { useFirstStepAction } from "@/features/first-steps/hooks/useFirstStepAction";
import { useFirstSteps } from "@/features/first-steps/hooks/useFirstSteps";

/**
 * The dashboard's activation card — one cell of the grid, built from the same
 * `BaseCardView` as every card beside it, so it cannot drift out of alignment
 * with them.
 *
 * No collapse control here, unlike the floating widget: this card sits in the
 * page flow with nothing underneath it to get out of the way, and the persisted
 * collapse is specifically about the panel that overlays the app.
 */
export function FirstStepsCard() {
  const { steps, isVisible } = useFirstSteps();
  const runStep = useFirstStepAction("dashboard");

  if (!isVisible) return null;

  return (
    <BaseCardView
      title="First steps"
      icon={<Rocket01Icon className="h-6 w-6 text-zinc-500" />}
      errorMessage="Failed to load your first steps"
    >
      <div className="space-y-2 p-4">
        {steps.map((step) => (
          <FirstStepRow
            key={step.key}
            step={step}
            onActivate={runStep}
            className="rounded-3xl bg-zinc-800/50 p-3 hover:bg-zinc-700/50"
          />
        ))}
      </div>
    </BaseCardView>
  );
}
