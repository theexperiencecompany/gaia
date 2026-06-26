/**
 * TriggerConnectionPrompt Component
 *
 * Standardized inline prompt shown when the integration backing a trigger
 * isn't connected yet. One canonical implementation for every handler — no
 * per-handler vertical cards.
 */

"use client";

import { Button } from "@heroui/button";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { TriggerConnectionPromptProps } from "./types";

export function TriggerConnectionPrompt({
  integrationName,
  integrationId,
  iconUrl,
  onConnect,
}: TriggerConnectionPromptProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-dashed border-zinc-600/70 bg-zinc-800/40 px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <div className="shrink-0">
          {getToolCategoryIcon(
            integrationId,
            { size: 22, width: 22, height: 22, showBackground: false },
            iconUrl,
          )}
        </div>
        <p className="min-w-0 text-sm text-zinc-300">
          Connect{" "}
          <span className="font-medium text-zinc-100">{integrationName}</span>{" "}
          to configure this trigger
        </p>
      </div>
      <Button
        color="primary"
        variant="flat"
        size="sm"
        className="shrink-0"
        onPress={onConnect}
      >
        Connect
      </Button>
    </div>
  );
}
