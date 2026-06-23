/**
 * TriggerConnectionPrompt Component
 *
 * Standardized connection prompt when integration is not connected
 */

"use client";

import { Button } from "@heroui/button";
import { Link01Icon } from "@icons";

import type { TriggerConnectionPromptProps } from "./types";

export function TriggerConnectionPrompt({
  integrationName,
  _integrationId,
  onConnect,
}: TriggerConnectionPromptProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-dashed border-zinc-700 px-4 py-3">
      <div className="flex items-center gap-2.5">
        <Link01Icon className="h-4 w-4 shrink-0 text-zinc-500" />
        <p className="text-sm text-zinc-400">
          Connect {integrationName} to use this trigger
        </p>
      </div>
      <Button color="primary" variant="flat" size="sm" onPress={onConnect}>
        Connect
      </Button>
    </div>
  );
}
