"use client";

import { Button } from "@heroui/button";
import { useState } from "react";
import type {
  CredentialProvider,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import type { ProviderCard } from "../../utils/providerCards";
import { ProviderSetupCard } from "../ProviderSetupCard";

interface HostedProviderLaneProps {
  /** Every chat provider card except Ollama, in catalog order. */
  cards: ProviderCard[];
  activeKey: CredentialProvider | undefined;
  status: SetupStatus;
  onSaved: () => unknown;
}

/** Hosted-key providers: the working one (or OpenRouter) leads, the rest sit behind "More providers". */
export function HostedProviderLane({
  cards,
  activeKey,
  status,
  onSaved,
}: HostedProviderLaneProps) {
  const [showAll, setShowAll] = useState(false);
  const primary =
    cards.find((c) => c.key === activeKey) ??
    cards.find((c) => c.key === "openrouter") ??
    cards[0];
  const ordered = primary
    ? [primary, ...cards.filter((c) => c !== primary)]
    : [];
  const visible = showAll ? ordered : ordered.slice(0, 1);

  return (
    <div className="flex flex-col gap-3">
      {visible.map((config) => (
        <ProviderSetupCard
          key={config.key}
          config={config}
          isConfigured={isProviderConfigured(status, config.key)}
          onSaved={onSaved}
        />
      ))}
      {ordered.length > 1 && (
        <Button
          variant="light"
          size="sm"
          radius="full"
          className="self-center text-zinc-500"
          onPress={() => setShowAll(!showAll)}
        >
          {showAll ? "Show fewer providers" : "More providers"}
        </Button>
      )}
    </div>
  );
}
