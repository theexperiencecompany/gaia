/**
 * Wizard stepper header — same visual language as the onboarding progress
 * bar: thin flex segments that fill with the primary accent as steps
 * complete. Uses a single navigation landmark with list semantics; each
 * segment is a listitem with aria-current="step" on the active dot.
 */

"use client";

import * as m from "motion/react-m";

interface WizardStepperProps {
  currentStep: number;
  totalSteps: number;
}

export function WizardStepper({ currentStep, totalSteps }: WizardStepperProps) {
  return (
    <nav aria-label="Setup progress">
      <ol className="mx-auto flex w-full max-w-xl items-center gap-2 px-4 py-5">
        {Array.from({ length: totalSteps }, (_, i) => i).map((index) => {
          const isCompleted = index < currentStep;
          const isCurrent = index === currentStep;
          const scaleXValue = isCompleted || isCurrent ? 1 : 0;

          return (
            <m.li
              key={`wizard-step-${String(index)}`}
              role="listitem"
              aria-current={isCurrent ? "step" : undefined}
              aria-label={`Step ${index + 1} of ${totalSteps}${isCompleted ? " completed" : ""}${isCurrent ? " current" : ""}`}
              className="relative h-0.5 flex-1 overflow-hidden rounded-full bg-zinc-800"
              initial={{ opacity: 0, scaleX: 0.8 }}
              animate={{ opacity: 1, scaleX: 1 }}
              transition={{ duration: 0.3, delay: index * 0.08 }}
            >
              <m.div
                className="absolute inset-0 origin-left rounded-full bg-primary"
                initial={{ scaleX: 0 }}
                animate={{ scaleX: scaleXValue }}
                transition={{ duration: 0.4, ease: "easeInOut" }}
              />
            </m.li>
          );
        })}
      </ol>
    </nav>
  );
}
