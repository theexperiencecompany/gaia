"use client";

import type { CredentialSource } from "@gaia/shared/api/generated";
import { Button } from "@heroui/button";
import { ProviderFavicon } from "@/features/settings/components/providers/ProviderFavicon";
import type { ProviderCard } from "../../utils/providerCards";

type ActiveSource = Exclude<CredentialSource, "unset">;

const SOURCE_COPY: Record<ActiveSource, string> = {
  env: "Set from the server's configuration, so GAIA can already chat.",
  stored: "Saved on this instance, so GAIA can already chat.",
};

interface ConnectedProviderCardProps {
  card: ProviderCard;
  source: ActiveSource;
  onChange: () => void;
}

/** The provider step's summary when a chat provider already works. */
export function ConnectedProviderCard({
  card,
  source,
  onChange,
}: ConnectedProviderCardProps) {
  return (
    <div className="flex w-full items-center gap-3 rounded-2xl bg-zinc-800 p-4">
      <ProviderFavicon domain={card.favicon_domain} size={32} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-zinc-100">
          {card.label} is connected
        </p>
        <p className="mt-0.5 text-xs text-zinc-400">{SOURCE_COPY[source]}</p>
      </div>
      <Button size="sm" variant="flat" radius="full" onPress={onChange}>
        Change provider
      </Button>
    </div>
  );
}
