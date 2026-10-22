"use client";

import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import type { WizardStepMeta } from "../constants";
import { AccountStep } from "./steps/AccountStep";
import { DoneStep } from "./steps/DoneStep";
import { FeatureStep } from "./steps/FeatureStep";
import { IntegrationsStep } from "./steps/IntegrationsStep";

interface WizardStepContentProps {
  stepId: WizardStepMeta["id"];
  status: SetupStatus;
  catalog: ProviderCatalog;
  onNext: () => void;
}

/** The body of the current wizard step. */
export function WizardStepContent({
  stepId,
  status,
  catalog,
  onNext,
}: WizardStepContentProps) {
  switch (stepId) {
    case "account":
      return <AccountStep onCreated={onNext} />;
    case "provider":
      return (
        <FeatureStep feature="ai_models" status={status} catalog={catalog} />
      );
    case "search":
      return (
        <FeatureStep feature="web_search" status={status} catalog={catalog} />
      );
    case "integrations":
      return <IntegrationsStep status={status} catalog={catalog} />;
    case "done":
      return <DoneStep status={status} catalog={catalog} />;
  }
}
