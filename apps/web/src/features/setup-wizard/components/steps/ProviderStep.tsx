/**
 * Wizard step 1 — pick and configure an AI provider (OpenRouter, Gemini,
 * OpenAI, Ollama, or a custom OpenAI-compatible endpoint). Every card saves and
 * tests independently; any single success unblocks continuing. An instance
 * that already chats opens on that provider's summary instead.
 */

"use client";

import * as m from "motion/react-m";
import { useState } from "react";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { activeLlmProvider } from "@/features/settings/hooks/useSetupStatus";
import { MOTION_FADE_UP } from "../../constants";
import { resolveLlmProviderCards } from "../../utils/providerCards";
import { ConnectedProviderCard } from "./ConnectedProviderCard";
import { HostedProviderLane } from "./HostedProviderLane";
import { OllamaProviderLane } from "./OllamaProviderLane";
import { type ProviderMode, ProviderModeTabs } from "./ProviderModeTabs";
import { SkipProviderNotice } from "./SkipProviderNotice";

interface ProviderStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
  /** Refetch setup status after a card connects, so Done reflects it. */
  onSaved: () => unknown;
  /** Advance the wizard (used by Ollama one-click and Skip). */
  onNext?: () => void;
}

export function ProviderStep({
  status,
  catalog,
  onSaved,
  onNext,
}: ProviderStepProps) {
  const activeKey = activeLlmProvider(status, catalog);
  const activeSource = activeKey && status.providers[activeKey]?.source;
  const [isChanging, setIsChanging] = useState(false);
  const [mode, setMode] = useState<ProviderMode>(
    activeKey === "ollama" ? "ollama" : "hosted",
  );

  const llmCards = resolveLlmProviderCards(catalog);
  const activeCard = llmCards.find((c) => c.key === activeKey);

  if (activeCard && activeSource && activeSource !== "unset" && !isChanging) {
    return (
      <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
        <ConnectedProviderCard
          card={activeCard}
          source={activeSource}
          onChange={() => setIsChanging(true)}
        />
      </m.div>
    );
  }

  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      <ProviderModeTabs mode={mode} onChange={setMode} />
      {mode === "hosted" && (
        <HostedProviderLane
          cards={llmCards.filter((c) => c.key !== "ollama")}
          activeKey={activeKey}
          status={status}
          onSaved={onSaved}
        />
      )}
      {mode === "ollama" && (
        <OllamaProviderLane
          card={llmCards.find((c) => c.key === "ollama")}
          status={status}
          onSaved={onSaved}
          onNext={onNext}
        />
      )}
      {mode === "skip" && <SkipProviderNotice onNext={onNext} />}
    </m.div>
  );
}
