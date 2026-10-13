/**
 * Wizard step 2 — optional web search via a Tavily API key. Same card
 * pattern as the provider step; entirely skippable.
 */

"use client";

import * as m from "motion/react-m";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { MOTION_FADE_UP, SEARCH_PROVIDER_CARD } from "../../constants";
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
      <ProviderSetupCard
        config={resolveProviderCard(SEARCH_PROVIDER_CARD, catalog)}
        isConfigured={isProviderConfigured(status, SEARCH_PROVIDER_CARD.key)}
        onSaved={onSaved}
      />
    </m.div>
  );
}
