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
import { useState } from "react";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import { ACCOUNT_STEP, WIZARD_STEPS } from "../constants";
import { useAccountStepGate } from "../hooks/useAccountStepGate";
import { WizardSteps } from "./WizardSteps";

export function SetupWizard() {
  const { data: status, isLoading, isError, refetch } = useSetupStatus();
  const catalogQuery = useProviderCatalog();
  const catalog = catalogQuery.data;
  const needsAccountStep = useAccountStepGate(status);
  const [stepIndex, setStepIndex] = useState(0);

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

  return (
    <WizardSteps
      steps={
        needsAccountStep === true
          ? [ACCOUNT_STEP, ...WIZARD_STEPS]
          : WIZARD_STEPS
      }
      stepIndex={stepIndex}
      onStepIndexChange={setStepIndex}
      status={status}
      catalog={catalog}
      refetchStatus={refetch}
    />
  );
}
