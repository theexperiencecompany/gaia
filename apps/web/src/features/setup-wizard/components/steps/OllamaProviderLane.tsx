"use client";

import type { SetupStatus } from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import type { ProviderCard } from "../../utils/providerCards";
import { ProviderSetupCard } from "../ProviderSetupCard";

interface OllamaProviderLaneProps {
  card: ProviderCard | undefined;
  status: SetupStatus;
  onSaved: () => unknown;
  onNext?: () => void;
}

/** Free local Ollama: one save connects it and advances the wizard. */
export function OllamaProviderLane({
  card,
  status,
  onSaved,
  onNext,
}: OllamaProviderLaneProps) {
  if (!card) {
    return (
      <div className="w-full rounded-2xl bg-zinc-800 p-4">
        <p className="text-sm text-zinc-400">
          This instance doesn&apos;t offer Ollama as a chat provider.
        </p>
      </div>
    );
  }

  const handleSaved = () => {
    // onSaved fires only after a successful save — advance once the status
    // refetch settles so the wizard reflects the new provider before moving.
    void Promise.resolve(onSaved()).then(
      () => onNext?.(),
      () => onNext?.(),
    );
  };

  return (
    <ProviderSetupCard
      config={card}
      isConfigured={isProviderConfigured(status, card.key)}
      onSaved={handleSaved}
    />
  );
}
