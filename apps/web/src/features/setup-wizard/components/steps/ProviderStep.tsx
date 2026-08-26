/**
 * Wizard step 1 — pick and configure an AI provider (OpenRouter, Gemini,
 * Ollama, or a custom OpenAI-compatible endpoint). Every card saves and
 * tests independently; any single success unblocks continuing.
 */

"use client";

import { Button } from "@heroui/button";
import { useQuery } from "@tanstack/react-query";
import * as m from "motion/react-m";
import { useState } from "react";
import {
  type CredentialProvider,
  type ProviderCatalog,
  providersApi,
  type SetupStatus,
} from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import {
  LLM_PROVIDER_CARDS,
  MOTION_FADE_UP,
  type ProviderCardConfig,
} from "../../constants";
import { ProviderSetupCard } from "../ProviderSetupCard";

type ProviderMode = "hosted" | "ollama" | "skip";

interface ProviderStepProps {
  status: SetupStatus;
  /** Refetch setup status after a card connects, so Done reflects it. */
  onSaved: () => void;
  /** Advance the wizard (used by Ollama one-click and Skip). */
  onNext?: () => void;
}

export function ProviderStep({ status, onSaved, onNext }: ProviderStepProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [mode, setMode] = useState<ProviderMode>("hosted");

  const { data: catalog } = useQuery<ProviderCatalog>({
    queryKey: ["setup", "catalog"],
    queryFn: () => providersApi.fetchCatalog(),
    staleTime: 60_000,
    retry: false,
  });

  // Prefer live catalog when available; fall back to the hardcoded LLM cards so
  // the wizard works even if the catalog endpoint is unreachable.
  const llmCards: ProviderCardConfig[] = catalog
    ? (catalog.llm_provider_keys as CredentialProvider[])
        .map<ProviderCardConfig | null>((key) => {
          const meta = catalog.providers[key];
          const fallback = LLM_PROVIDER_CARDS.find((c) => c.key === key);
          if (!meta && !fallback) return null;
          // Catalog has no description/connectionTestable — carry them from the
          // hardcoded card so UI shape stays identical.
          const card: ProviderCardConfig = {
            key,
            label: meta?.label || fallback?.label || key,
            description: fallback?.description || meta?.description || "",
            faviconDomain:
              meta?.favicon_domain || fallback?.faviconDomain || "",
            showApiKey: fallback?.showApiKey ?? true,
            showBaseUrl: meta?.needs_base_url ?? fallback?.showBaseUrl ?? false,
            showModel: fallback?.showModel ?? false,
            connectionTestable: fallback?.connectionTestable ?? true,
            defaultBaseUrl:
              meta?.base_url ||
              meta?.default_base_url ||
              fallback?.defaultBaseUrl ||
              "",
            defaultModel: meta?.default_model || fallback?.defaultModel || "",
            hasPresets: fallback?.hasPresets ?? false,
          };
          if (fallback?.presetFavicon)
            card.presetFavicon = fallback.presetFavicon;
          return card;
        })
        .filter((c): c is ProviderCardConfig => c !== null)
    : LLM_PROVIDER_CARDS;

  const openRouterCard =
    llmCards.find((c) => c.key === "openrouter") ?? llmCards[0];
  const ollamaCard = llmCards.find((c) => c.key === "ollama");

  // Hosted lane — every LLM card except Ollama. Ollama gets its own top-level
  // tab so self-hosters without a key see a clear "free, no key needed" path.
  const hostedCards = llmCards.filter((c) => c.key !== "ollama");
  const hostedPrimary =
    hostedCards.find((c) => c.key === openRouterCard?.key) ?? hostedCards[0];
  const hostedOthers = hostedCards.filter((c) => c.key !== hostedPrimary?.key);

  const handleOllamaSaved = () => {
    onSaved();
    // Let the status refetch land, then advance so the wizard reflects the new
    // provider before moving on.
    window.setTimeout(() => onNext?.(), 400);
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
                Ollama configuration is unavailable — the provider catalog
                couldn&apos;t be loaded. Try reloading the page.
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
              Settings → AI Providers
            </span>
            . Until then GAIA will use local fallbacks where available.
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
