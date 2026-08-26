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

interface ProviderStepProps {
  status: SetupStatus;
  /** Refetch setup status after a card connects, so Done reflects it. */
  onSaved: () => void;
}

export function ProviderStep({ status, onSaved }: ProviderStepProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

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
  const otherCards = llmCards.filter((c) => c.key !== openRouterCard?.key);

  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      {openRouterCard && (
        <ProviderSetupCard
          key={openRouterCard.key}
          config={openRouterCard}
          isConfigured={isProviderConfigured(status, openRouterCard.key)}
          onSaved={onSaved}
        />
      )}
      {otherCards.length > 0 &&
        (showAdvanced ? (
          <div className="flex flex-col gap-3">
            {otherCards.map((config) => (
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
    </m.div>
  );
}
