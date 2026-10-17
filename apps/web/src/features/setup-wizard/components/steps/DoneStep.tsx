/**
 * Wizard step 4 — summary of everything configured, then off to chat. The
 * celebratory "ready" card + starter prompts make the empty chat feel
 * intentional; the skipped-provider branch nudges toward Settings without
 * blocking. Done-ness is live-derived (needs_setup), never recorded.
 */

"use client";

import * as m from "motion/react-m";
import { useEffect } from "react";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  isAnyLlmConfigured,
  isFeatureWorking,
  isProviderConfigured,
} from "@/features/settings/hooks/useSetupStatus";
import { featureEngineLabel } from "@/features/settings/utils/providerCatalog";
import { TOOL_PROVIDER_CARDS } from "../../constants";
import {
  resolveLlmProviderCards,
  resolveProviderCard,
} from "../../utils/providerCards";
import { DoneActions } from "./done/DoneActions";
import { ReadyCard } from "./done/ReadyCard";
import { SetupSummaryCard } from "./done/SetupSummaryCard";
import { SkippedProviderCard } from "./done/SkippedProviderCard";
import { StarterPromptsCard } from "./done/StarterPromptsCard";
import { STARTER_PROMPTS } from "./done/starterPrompts";

interface DoneStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
}

export function DoneStep({ status, catalog }: DoneStepProps) {
  const connectedLlmCards = resolveLlmProviderCards(catalog).filter((card) =>
    isProviderConfigured(status, card.key),
  );
  const hasLlm = isAnyLlmConfigured(status, catalog);

  const [searchEngine] = status.features.web_search?.in_use ?? [];
  const searchLabel = searchEngine
    ? featureEngineLabel(searchEngine, catalog.features.web_search, catalog)
    : null;

  const connectedTools = TOOL_PROVIDER_CARDS.filter((card) =>
    isProviderConfigured(status, card.key),
  ).map((card) => resolveProviderCard(card, catalog));

  const starterPrompts = STARTER_PROMPTS.filter(
    (item) => !item.requires || isFeatureWorking(status, item.requires),
  );
  const someFeatureOff = Object.values(status.features).some(
    (feature) => !feature.working,
  );

  // Subtle confetti burst when the GAIA is ready — single fire, no loop.
  useEffect(() => {
    if (!hasLlm) return;
    let cancelled = false;
    import("canvas-confetti")
      .then(({ default: confetti }) => {
        if (cancelled) return;
        confetti({
          particleCount: 90,
          spread: 70,
          origin: { y: 0.65 },
          ticks: 180,
          gravity: 1.1,
          decay: 0.94,
          scalar: 0.9,
          colors: ["#00bbff", "#a78bfa", "#34d399", "#f472b6"],
        });
      })
      .catch((error: unknown) => {
        console.error("Failed to load the confetti burst:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [hasLlm]);

  return (
    <m.div
      className="flex w-full flex-col gap-3"
      initial="hidden"
      animate="visible"
      variants={{
        hidden: {},
        visible: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
      }}
    >
      {hasLlm ? (
        <ReadyCard connectedLlmCards={connectedLlmCards} />
      ) : (
        <SkippedProviderCard />
      )}
      {hasLlm && <StarterPromptsCard prompts={starterPrompts} />}
      <SetupSummaryCard
        connectedLlmCards={connectedLlmCards}
        searchLabel={searchLabel}
        connectedTools={connectedTools}
        hasAdminAccount={status.has_admin_account}
      />
      <DoneActions hasLlm={hasLlm} />
      {someFeatureOff && (
        <m.p
          variants={{
            hidden: { opacity: 0 },
            visible: { opacity: 1 },
          }}
          transition={{ duration: 0.35, delay: 0.2 }}
          className="text-center text-xs text-zinc-500"
        >
          Skipped something? You can finish anytime in Settings, under Providers
          & Tools.
        </m.p>
      )}
    </m.div>
  );
}
