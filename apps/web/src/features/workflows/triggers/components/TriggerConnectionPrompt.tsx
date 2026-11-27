/**
 * TriggerConnectionPrompt Component
 *
 * Standardized inline prompt shown when the integration backing a trigger
 * isn't connected yet. One canonical implementation for every handler — no
 * per-handler vertical cards. The integration's name and icon come from the
 * catalog, never from the handler.
 */

"use client";

import { Skeleton } from "@heroui/react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { TriggerConnectionPromptProps } from "./types";

const PROMPT_CLASS =
  "flex items-center justify-between gap-3 rounded-2xl border border-dashed border-zinc-600/70 bg-zinc-800/40 px-4 py-3";

export function TriggerConnectionPrompt({
  integrationId,
}: TriggerConnectionPromptProps) {
  const { integrations, isLoading, connectIntegration } = useIntegrations();
  const integration = integrations.find((i) => i.id === integrationId);

  if (!integration) {
    return isLoading ? (
      <Skeleton className="h-14 w-full rounded-2xl" />
    ) : (
      <div className={PROMPT_CLASS}>
        <p className="text-sm text-zinc-400">
          This trigger&apos;s integration isn&apos;t available on this GAIA
          instance.
        </p>
      </div>
    );
  }

  return (
    <div className={PROMPT_CLASS}>
      <div className="flex min-w-0 items-center gap-3">
        <div className="shrink-0">
          <IntegrationIcon
            integrationId={integration.id}
            iconUrl={integration.iconUrl}
            size={22}
          />
        </div>
        <p className="min-w-0 text-sm text-zinc-300">
          Connect{" "}
          <span className="font-medium text-zinc-100">{integration.name}</span>{" "}
          to configure this trigger
        </p>
      </div>
      <GaiaButton
        variant="accent-soft"
        size="sm"
        className="shrink-0"
        onPress={() => connectIntegration(integration.id)}
      >
        Connect
      </GaiaButton>
    </div>
  );
}
