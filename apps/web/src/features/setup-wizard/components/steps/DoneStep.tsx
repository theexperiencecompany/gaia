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
  CredentialProvider,
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  isAnyLlmConfigured,
  isProviderConfigured,
} from "@/features/settings/hooks/useSetupStatus";
import {
  LLM_PROVIDER_CARDS,
  SEARCH_PROVIDER_CARD,
  TOOL_PROVIDER_CARDS,
  WIZARD_EXCLUDED_TOOL_KEYS,
} from "../../constants";
import { DoneActions } from "./done/DoneActions";
import { ReadyCard } from "./done/ReadyCard";
import { SetupSummaryCard } from "./done/SetupSummaryCard";
import { SkippedProviderCard } from "./done/SkippedProviderCard";
import { StarterPromptsCard } from "./done/StarterPromptsCard";
import { STARTER_PROMPTS, type StarterPrompt } from "./done/starterPrompts";

interface DoneStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
}

export function DoneStep({ status, catalog }: DoneStepProps) {
  const connectedLlmCards = LLM_PROVIDER_CARDS.filter((card) =>
    isProviderConfigured(status, card.key),
  );
  const hasLlm = isAnyLlmConfigured(status, catalog);

  const searchConfigured = isProviderConfigured(
    status,
    SEARCH_PROVIDER_CARD.key,
  );

  const connectedTools = TOOL_PROVIDER_CARDS.filter(
    (card) =>
      !(WIZARD_EXCLUDED_TOOL_KEYS as readonly string[]).includes(card.key) &&
      isProviderConfigured(status, card.key),
  );
  const toolConfigured = (key: CredentialProvider) =>
    connectedTools.some((card) => card.key === key);

  // Code runs on E2B or the operator's opt-in local sandbox; the inbox needs
  // Composio — every other prompt needs its key configured.
  const capabilityReady = (requires: StarterPrompt["requires"]): boolean => {
    if (!requires) return true;
    if (requires === "sandbox")
      return toolConfigured("e2b") || status.local_code_sandbox === true;
    if (requires === "inbox") return toolConfigured("composio");
    return isProviderConfigured(status, requires);
  };

  const starterPrompts = STARTER_PROMPTS.filter((item) =>
    capabilityReady(item.requires),
  );

  // Subtle confetti burst when the GAIA is ready — single fire, no loop.
  useEffect(() => {
    if (!hasLlm) return;
    let cancelled = false;
    import("canvas-confetti").then(({ default: confetti }) => {
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
        searchLabel={searchConfigured ? SEARCH_PROVIDER_CARD.label : null}
        connectedTools={connectedTools}
        hasAdminAccount={status.has_admin_account}
      />
      <DoneActions hasLlm={hasLlm} />
      {!searchConfigured && (
        <m.p
          variants={{
            hidden: { opacity: 0 },
            visible: { opacity: 1 },
          }}
          transition={{ duration: 0.35, delay: 0.2 }}
          className="text-center text-xs text-zinc-500"
        >
          Skipped something? You can finish anytime in Settings, under AI
          Providers.
        </m.p>
      )}
    </m.div>
  );
}
