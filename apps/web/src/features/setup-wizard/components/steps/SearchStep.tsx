/**
 * Wizard step 2 — optional web search via a Tavily API key. Same card
 * pattern as the provider step; entirely skippable.
 */

"use client";

import * as m from "motion/react-m";
import type { SetupStatus } from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { MOTION_FADE_UP, SEARCH_PROVIDER_CARD } from "../../constants";
import { ProviderSetupCard } from "../ProviderSetupCard";

interface SearchStepProps {
  status: SetupStatus;
  onSaved: () => void;
}

export function SearchStep({ status, onSaved }: SearchStepProps) {
  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      <ProviderSetupCard
        config={SEARCH_PROVIDER_CARD}
        isConfigured={isProviderConfigured(status, SEARCH_PROVIDER_CARD.key)}
        onSaved={onSaved}
      />
    </m.div>
  );
}
