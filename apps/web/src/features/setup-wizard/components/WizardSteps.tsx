"use client";

import { Chip } from "@heroui/chip";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useState } from "react";
import {
  type ProviderCatalog,
  providersApi,
  type SetupStatus,
} from "@/features/settings/api/providersApi";
import { isAnyLlmConfigured } from "@/features/settings/hooks/useSetupStatus";
import type { WizardStepMeta } from "../constants";
import { WizardFooter } from "./WizardFooter";
import { WizardStepContent } from "./WizardStepContent";
import { WizardStepper } from "./WizardStepper";

const WALLPAPER_STYLE = {
  backgroundImage: "url('/images/wallpapers/bands_gradient_black.png')",
} as const;

// One-line reason shown under the footer once Continue is pressed too early.
const CONTINUE_REASONS: Record<string, string> = {
  provider: "Chat requires a provider — add one to start chatting.",
};

function continueReasonFor(stepId: string, objectiveMet: boolean) {
  if (objectiveMet) return null;
  return CONTINUE_REASONS[stepId] ?? null;
}

/** Whether Continue may advance: only the required steps (admin, AI provider) can hold it. */
function isStepObjectiveMet(
  stepId: WizardStepMeta["id"],
  status: SetupStatus,
  catalog: ProviderCatalog,
): boolean {
  switch (stepId) {
    case "account":
      return status.has_admin_account;
    case "provider":
      return isAnyLlmConfigured(status, catalog);
    default:
      return true;
  }
}

interface WizardStepsProps {
  steps: readonly WizardStepMeta[];
  stepIndex: number;
  onStepIndexChange: (update: (index: number) => number) => void;
  status: SetupStatus;
  catalog: ProviderCatalog;
}

/** The wizard once its setup status has loaded: stepper, the current step, and its footer. */
export function WizardSteps({
  steps,
  stepIndex,
  onStepIndexChange,
  status,
  catalog,
}: WizardStepsProps) {
  // The step whose Continue was pressed before its objective was met.
  const [blockedStepId, setBlockedStepId] = useState<string | null>(null);

  const lastStepIndex = steps.length - 1;
  const step = steps[stepIndex];
  const isLastStep = stepIndex === lastStepIndex;

  const stepObjectiveMet = isStepObjectiveMet(step.id, status, catalog);
  // Creating the account advances the wizard itself, and the step has no
  // Back or Skip, so until the account exists there is nothing to offer.
  const awaitingAccount = step.id === "account" && !stepObjectiveMet;

  const goNext = () => onStepIndexChange((i) => Math.min(i + 1, lastStepIndex));
  const goBack = () => onStepIndexChange((i) => Math.max(i - 1, 0));

  // Derived from the same objective check above, and only after an attempt:
  // a warning before the user has done anything reads as an error.
  const continueReason =
    blockedStepId === step.id
      ? continueReasonFor(step.id, stepObjectiveMet)
      : null;
  const tryContinue = () => {
    if (stepObjectiveMet) goNext();
    else setBlockedStepId(step.id);
  };
  // Skipping the provider unmet is the admin opting out: the wizard stops
  // reopening and the chat setup banner nudges instead.
  const skip = async () => {
    if (step.id === "provider" && !stepObjectiveMet) {
      try {
        await providersApi.dismissSetupWizard();
      } catch {
        return; // the API client already toasted; stay on the step
      }
    }
    goNext();
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-primary-bg backdrop-blur-2xl">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 bg-center bg-cover opacity-40"
        style={WALLPAPER_STYLE}
      />

      <div className="relative z-10">
        <WizardStepper currentStep={stepIndex} totalSteps={steps.length} />
      </div>

      <div className="relative z-10 flex-1 overflow-y-auto px-4 pb-16">
        <div className="mx-auto w-full max-w-xl">
          <AnimatePresence mode="wait">
            <m.div
              key={`wizard-heading-${step.id}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            >
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-semibold tracking-tight text-white">
                  {step.title}
                </h1>
                {step.optional && (
                  <Chip size="sm" variant="flat">
                    Optional
                  </Chip>
                )}
              </div>
              <p className="mt-3 mb-8 text-sm leading-relaxed text-zinc-400">
                {step.subtitle}
              </p>
            </m.div>
          </AnimatePresence>

          <AnimatePresence mode="wait">
            <m.div
              key={`wizard-content-${step.id}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.25, ease: "easeOut" }}
            >
              <WizardStepContent
                stepId={step.id}
                status={status}
                catalog={catalog}
                onNext={goNext}
              />
            </m.div>
          </AnimatePresence>

          {!isLastStep && !awaitingAccount && (
            <WizardFooter
              onBack={stepIndex > 0 ? goBack : null}
              onContinue={tryContinue}
              // The account step has no skip: without its session every
              // later wizard write would bounce off auth.
              onSkip={step.id === "account" ? null : skip}
              continueReason={continueReason}
            />
          )}
        </div>
      </div>
    </div>
  );
}
