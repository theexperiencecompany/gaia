/**
 * First-run self-host setup wizard. One full-screen shell (onboarding-style
 * wallpaper + stepper header + Inter heading) hosting the steps:
 * admin account (fresh local-auth instances), AI provider, web search,
 * account connections, done. Instances that don't need setup never reach it
 * (the setup page redirects them server-side). Never traps the user: every step has an escape hatch ("Skip for now" or Back); the account
 * step is the one exception because nothing else in the wizard can work
 * without its session.
 */

"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Alert01Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { useLoginModalActions } from "@/features/auth/hooks/useLoginModal";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import {
  isAnyLlmConfigured,
  isProviderConfigured,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";
import { ACCOUNT_STEP, WIZARD_STEPS, type WizardStepMeta } from "../constants";
import { AccountStep } from "./steps/AccountStep";
import { DoneStep } from "./steps/DoneStep";
import { IntegrationsStep } from "./steps/IntegrationsStep";
import { ProviderStep } from "./steps/ProviderStep";
import { SearchStep } from "./steps/SearchStep";
import { WizardFooter } from "./WizardFooter";
import { WizardStepper } from "./WizardStepper";

const WALLPAPER_STYLE = {
  backgroundImage: "url('/images/wallpapers/bands_gradient_black.png')",
} as const;

// One-line reason shown under the footer once Continue is pressed too early.
const CONTINUE_REASONS: Record<string, string> = {
  account: "Create the admin account above to continue.",
  provider: "Chat requires a provider — add one to start chatting.",
  search: "Add a search key to continue, or skip this step.",
};

function continueReasonFor(stepId: string, objectiveMet: boolean) {
  if (objectiveMet) return null;
  return CONTINUE_REASONS[stepId] ?? null;
}

/** Each step's objective — Continue advances once met; Skip always escapes. */
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
    case "search":
      return isProviderConfigured(status, "tavily");
    default:
      return true;
  }
}

export function SetupWizard() {
  const { data: status, isLoading, isError, refetch } = useSetupStatus();
  const catalogQuery = useProviderCatalog();
  const catalog = catalogQuery.data;
  const { suppressModal, unsuppressModal } = useLoginModalActions();
  const [stepIndex, setStepIndex] = useState(0);
  // The step whose Continue was pressed before its objective was met.
  const [blockedStepId, setBlockedStepId] = useState<string | null>(null);

  // Whether the wizard leads with account creation — captured from the FIRST
  // status load so the step list can't shift underneath the stepper once the
  // account exists (creating it flips has_admin_account mid-wizard).
  const [needsAccountStep, setNeedsAccountStep] = useState<boolean | null>(
    null,
  );

  if (status && needsAccountStep === null) {
    setNeedsAccountStep(
      status.auth_mode === "local" && !status.has_admin_account,
    );
  }

  // While the wizard owns authentication (its own signup form below), the
  // global login modal must stay out of the way: its only action redirects
  // to WorkOS OAuth, which does not exist on self-host instances.
  useEffect(() => {
    if (!needsAccountStep) return;
    suppressModal();
    return () => unsuppressModal();
  }, [needsAccountStep, suppressModal, unsuppressModal]);

  const steps =
    needsAccountStep === true ? [ACCOUNT_STEP, ...WIZARD_STEPS] : WIZARD_STEPS;
  const lastStepIndex = steps.length - 1;

  if (
    isLoading ||
    catalogQuery.isLoading ||
    (needsAccountStep === null && !isError)
  ) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-primary-bg">
        <Spinner size="lg" />
      </div>
    );
  }

  // Error screen — unreachable while loading or once status has resolved;
  // a failed status or catalog fetch must surface instead of spinning forever.
  if (isError || status === undefined || catalog === undefined) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-primary-bg px-4 text-center">
        <Alert01Icon size={24} className="text-zinc-500" />
        <p className="text-sm text-zinc-400">
          Couldn't reach your GAIA instance to check its setup status.
        </p>
        <Button
          variant="flat"
          onPress={() => {
            void refetch();
            void catalogQuery.refetch();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  const step = steps[stepIndex];
  const isLastStep = stepIndex === lastStepIndex;

  const stepObjectiveMet = isStepObjectiveMet(step.id, status, catalog);

  const goNext = () => setStepIndex((i) => Math.min(i + 1, lastStepIndex));
  const goBack = () => setStepIndex((i) => Math.max(i - 1, 0));
  const refreshStatus = () => void refetch();

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
              <h1 className="text-2xl font-semibold tracking-tight text-white">
                {step.title}
              </h1>
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
              {step.id === "account" && (
                <AccountStep
                  onCreated={() => {
                    refreshStatus();
                    goNext();
                  }}
                />
              )}
              {step.id === "provider" && (
                <ProviderStep
                  status={status}
                  catalog={catalog}
                  // Return the refetch promise (not void) so Ollama one-click
                  // can advance after it settles.
                  onSaved={() => refetch()}
                  onNext={goNext}
                />
              )}
              {step.id === "search" && (
                <SearchStep
                  status={status}
                  catalog={catalog}
                  onSaved={refreshStatus}
                />
              )}
              {step.id === "integrations" && (
                <IntegrationsStep
                  status={status}
                  catalog={catalog}
                  onSaved={refreshStatus}
                />
              )}
              {step.id === "done" && (
                <DoneStep status={status} catalog={catalog} />
              )}
            </m.div>
          </AnimatePresence>

          {!isLastStep && (
            <WizardFooter
              onBack={stepIndex > 0 ? goBack : null}
              onContinue={tryContinue}
              // The account step has no skip: without its session every
              // later wizard write would bounce off auth.
              onSkip={step.id === "account" ? null : goNext}
              continueReason={continueReason}
            />
          )}
        </div>
      </div>
    </div>
  );
}
