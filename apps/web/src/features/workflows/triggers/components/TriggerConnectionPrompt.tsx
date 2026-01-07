/**
 * TriggerConnectionPrompt Component
 *
 * Standardized connection prompt when integration is not connected
 */

"use client";

import { Button } from "@heroui/button";

import type { TriggerConnectionPromptProps } from "./types";

export function TriggerConnectionPrompt({
  integrationName,
  _integrationId,
  onConnect,
}: TriggerConnectionPromptProps) {
  return (
    <div className="flex flex-col items-center justify-center p-4 space-y-3 bg-zinc-900/50 rounded-lg border border-zinc-800">
      <p className="text-sm text-zinc-400">
        Connect {integrationName} to configure this trigger
      </p>
      <Button color="primary" variant="flat" onPress={onConnect}>
        Connect {integrationName}
      </Button>
    </div>
  );
}
