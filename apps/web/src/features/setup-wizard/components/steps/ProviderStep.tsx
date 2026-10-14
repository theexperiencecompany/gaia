/**
 * Wizard step 1 — pick and configure an AI provider (OpenRouter, Gemini,
 * OpenAI, Ollama, or a custom OpenAI-compatible endpoint). Every card saves and
 * tests independently; any single success unblocks continuing. An instance
 * that already chats opens on that provider's summary instead.
 */

"use client";

import { Button } from "@heroui/button";
import * as m from "motion/react-m";
import { useState } from "react";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  activeLlmProvider,
  isProviderConfigured,
} from "@/features/settings/hooks/useSetupStatus";
import { MOTION_FADE_UP } from "../../constants";
import { resolveLlmProviderCards } from "../../utils/providerCards";
import { ProviderSetupCard } from "../ProviderSetupCard";
import { ConnectedProviderCard } from "./ConnectedProviderCard";

type ProviderMode = "hosted" | "ollama" | "skip";

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
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [mode, setMode] = useState<ProviderMode>(
    activeKey === "ollama" ? "ollama" : "hosted",
  );

  const llmCards = resolveLlmProviderCards(catalog);
  const activeCard = llmCards.find((c) => c.key === activeKey);
  const ollamaCard = llmCards.find((c) => c.key === "ollama");

  // Hosted lane — every LLM card except Ollama. Ollama gets its own top-level
  // tab so self-hosters without a key see a clear "free, no key needed" path.
  // The working provider leads it; a fresh instance starts on OpenRouter.
  const hostedCards = llmCards.filter((c) => c.key !== "ollama");
  const hostedPrimary =
    hostedCards.find((c) => c.key === activeKey) ??
    hostedCards.find((c) => c.key === "openrouter") ??
    hostedCards[0];
  const hostedOthers = hostedCards.filter((c) => c.key !== hostedPrimary?.key);

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

  const handleOllamaSaved = () => {
    // onSaved fires only after a successful save — advance once the status
    // refetch settles so the wizard reflects the new provider before moving.
    void Promise.resolve(onSaved()).then(
      () => onNext?.(),
      () => onNext?.(),
    );
  };

  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      {/* Top-level choice — the "I have nothing, just make it work" path is
          now a first-class tab, not buried inside a card. */}
      <div className="flex gap-1 rounded-full bg-zinc-900 p-1">
        {(
          [
            { key: "hosted" as const, label: "Hosted key" },
            { key: "ollama" as const, label: "Local Ollama · free" },
            { key: "skip" as const, label: "Skip for now" },
          ] as const
        ).map((tab) => {
          const selected = mode === tab.key;
          return (
            <Button
              key={tab.key}
              size="sm"
              radius="full"
              variant={selected ? "solid" : "light"}
              color={selected ? "primary" : "default"}
              className={
                selected
                  ? "flex-1 font-medium"
                  : "flex-1 font-medium text-zinc-400"
              }
              onPress={() => setMode(tab.key)}
            >
              {tab.label}
            </Button>
          );
        })}
      </div>

      {mode === "hosted" && (
        <div className="flex flex-col gap-3">
          {hostedPrimary && (
            <ProviderSetupCard
              key={hostedPrimary.key}
              config={hostedPrimary}
              isConfigured={isProviderConfigured(status, hostedPrimary.key)}
              onSaved={onSaved}
            />
          )}
          {hostedOthers.length > 0 &&
            (showAdvanced ? (
              <div className="flex flex-col gap-3">
                {hostedOthers.map((config) => (
                  <ProviderSetupCard
                    key={config.key}
                    config={config}
                    isConfigured={isProviderConfigured(status, config.key)}
                    onSaved={onSaved}
                  />
                ))}
                <Button
                  variant="light"
                  size="sm"
                  radius="full"
                  className="self-center text-zinc-500"
                  onPress={() => setShowAdvanced(false)}
                >
                  Show fewer providers
                </Button>
              </div>
            ) : (
              <Button
                variant="light"
                size="sm"
                radius="full"
                className="self-center text-zinc-500"
                onPress={() => setShowAdvanced(true)}
              >
                More providers
              </Button>
            ))}
        </div>
      )}

      {mode === "ollama" && (
        <div className="flex flex-col gap-3">
          {ollamaCard ? (
            <ProviderSetupCard
              key={ollamaCard.key}
              config={ollamaCard}
              isConfigured={isProviderConfigured(status, ollamaCard.key)}
              onSaved={handleOllamaSaved}
            />
          ) : (
            <div className="w-full rounded-2xl bg-zinc-800 p-4">
              <p className="text-sm text-zinc-400">
                This instance doesn&apos;t offer Ollama as a chat provider.
              </p>
            </div>
          )}
        </div>
      )}

      {mode === "skip" && (
        <div className="w-full rounded-2xl bg-zinc-800 p-4">
          <p className="text-sm font-medium text-zinc-100">
            Skip provider setup for now
          </p>
          <p className="mt-1 text-sm leading-relaxed text-zinc-400">
            You can add a provider later in{" "}
            <span className="font-medium text-zinc-300">
              Settings, under AI Providers
            </span>
            . Without a provider, chat can&apos;t reply yet.
          </p>
          {onNext && (
            <Button
              size="sm"
              color="primary"
              variant="flat"
              className="mt-3"
              onPress={onNext}
            >
              Continue without a provider
            </Button>
          )}
        </div>
      )}
    </m.div>
  );
}
