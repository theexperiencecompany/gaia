"use client";

import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import type { WizardStepMeta } from "../constants";
import { AccountStep } from "./steps/AccountStep";
import { DoneStep } from "./steps/DoneStep";
import { IntegrationsStep } from "./steps/IntegrationsStep";
import { ProviderStep } from "./steps/ProviderStep";
import { SearchStep } from "./steps/SearchStep";

interface WizardStepContentProps {
  stepId: WizardStepMeta["id"];
  status: SetupStatus;
  catalog: ProviderCatalog;
  /** Refetches setup status; resolves once the new status has landed. */
  refetchStatus: () => Promise<unknown>;
  onNext: () => void;
}

/** The body of the current wizard step. */
export function WizardStepContent({
  stepId,
  status,
  catalog,
  refetchStatus,
  onNext,
}: WizardStepContentProps) {
  const refreshStatus = () => void refetchStatus();

  switch (stepId) {
    case "account":
      return (
        <AccountStep
          onCreated={() => {
            refreshStatus();
            onNext();
          }}
        />
      );
    case "provider":
      return (
        <ProviderStep
          status={status}
          catalog={catalog}
          // Return the refetch promise (not void) so Ollama one-click can
          // advance after it settles.
          onSaved={refetchStatus}
          onNext={onNext}
        />
      );
    case "search":
      return (
        <SearchStep status={status} catalog={catalog} onSaved={refreshStatus} />
      );
    case "integrations":
      return (
        <IntegrationsStep
          status={status}
          catalog={catalog}
          onSaved={refreshStatus}
        />
      );
    case "done":
      return <DoneStep status={status} catalog={catalog} />;
  }
}
