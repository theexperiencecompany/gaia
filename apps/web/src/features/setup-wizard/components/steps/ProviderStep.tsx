/**
 * Wizard step 1 — pick and configure an AI provider (OpenRouter, Gemini,
 * Ollama, or a custom OpenAI-compatible endpoint). Every card saves and
 * tests independently; any single success unblocks continuing.
 */

"use client";

import * as m from "motion/react-m";
import type { SetupStatus } from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { LLM_PROVIDER_CARDS, MOTION_FADE_UP } from "../../constants";
import { ProviderSetupCard } from "../ProviderSetupCard";

interface ProviderStepProps {
  status: SetupStatus;
  /** Refetch setup status after a card connects, so Done reflects it. */
  onSaved: () => void;
}

export function ProviderStep({ status, onSaved }: ProviderStepProps) {
  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      {LLM_PROVIDER_CARDS.map((config) => (
        <ProviderSetupCard
          key={config.key}
          config={config}
          isConfigured={isProviderConfigured(status, config.key)}
          onSaved={onSaved}
        />
      ))}
    </m.div>
  );
}
