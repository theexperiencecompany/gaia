"use client";

import { Button } from "@heroui/button";
import { Switch } from "@heroui/switch";
import { toolAsks } from "@shared/chat";
import { useMemo } from "react";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { toast } from "@/lib/toast";

interface IntegrationToolApprovalsProps {
  tools: IntegrationToolEntry[];
  /** Mode is `always_allow`: same list, read-only, with a prompt to turn approvals on. */
  disabled?: boolean;
}

/**
 * Which tools of a connected integration need approval. A switch on puts the tool
 * in the gated set — the set that `always_ask` prompts on and `auto` runs the
 * intent judge over. Order is fixed on the default classification (gated-first)
 * so toggling never reorders rows.
 */
export const IntegrationToolApprovals = ({
  tools,
  disabled = false,
}: IntegrationToolApprovalsProps) => {
  const { prefs, setToolApproval, setMode, isSavingMode } = useHilPreferences();

  const handleEnable = async () => {
    try {
      await setMode("always_ask");
    } catch {
      toast.error("Failed to turn on approvals");
    }
  };

  const ordered = useMemo(
    () =>
      [...tools].sort((a, b) => Number(b.destructive) - Number(a.destructive)),
    [tools],
  );

  return (
    <div>
      {disabled && (
        <div className="mb-2 flex items-center justify-between gap-2 rounded-xl bg-zinc-800/60 px-3 py-2">
          <span className="text-xs text-zinc-400">
            GAIA runs these without asking.
          </span>
          <Button
            size="sm"
            variant="flat"
            isLoading={isSavingMode}
            onPress={handleEnable}
          >
            Turn on
          </Button>
        </div>
      )}
      <div>
        {ordered.map((tool) => {
          const ask = toolAsks(prefs, tool.name, tool.destructive);
          return (
            <div
              key={tool.name}
              className="flex items-center justify-between gap-3 py-1.5"
            >
              <span className="truncate text-sm text-zinc-300">
                {tool.label}
              </span>
              <Switch
                size="sm"
                isSelected={ask}
                isDisabled={disabled}
                onValueChange={(v) =>
                  setToolApproval(tool.name, v, tool.destructive)
                }
                aria-label={`Require approval for ${tool.label}`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};
