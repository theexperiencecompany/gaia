/**
 * Wizard step 2 — web search already works keyless; optional Tavily, Exa or
 * Brave keys improve it. Same card pattern as the provider step; entirely
 * skippable.
 */

"use client";

import * as m from "motion/react-m";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { MOTION_FADE_UP, SEARCH_PROVIDER_CARDS } from "../../constants";
import { resolveProviderCard } from "../../utils/providerCards";
import { ProviderSetupCard } from "../ProviderSetupCard";

interface SearchStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
  onSaved: () => void;
}

export function SearchStep({ status, catalog, onSaved }: SearchStepProps) {
  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      {SEARCH_PROVIDER_CARDS.map((card) => (
        <ProviderSetupCard
          key={card.key}
          config={resolveProviderCard(card, catalog)}
          isConfigured={isProviderConfigured(status, card.key)}
          onSaved={onSaved}
        />
      ))}
    </m.div>
  );
}
