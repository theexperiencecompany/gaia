"use client";

import { Button } from "@heroui/button";
import { Switch } from "@heroui/switch";
import { ShieldIcon } from "@icons";
import { useMemo } from "react";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";
import {
  toolAsks,
  useHilPreferences,
} from "@/features/settings/hooks/useHilPreferences";
import { toast } from "@/lib/toast";

interface IntegrationToolApprovalsProps {
  tools: IntegrationToolEntry[];
  /** HIL is off globally: show the same list, but read-only with an enable prompt. */
  disabled?: boolean;
}

/**
 * Per-tool approval switches for a connected integration. Each switch reflects
 * `override ?? tool.destructive`; flipping it stores a diff via HIL prefs. Order
 * is fixed on the default gating (gated-first) so toggling never reorders rows.
 * The layout is identical whether HIL is on or off — off just disables the
 * switches and shows an enable prompt — so the view never changes shape.
 */
export const IntegrationToolApprovals = ({
  tools,
  disabled = false,
}: IntegrationToolApprovalsProps) => {
  const { prefs, setToolApproval, setEnabled, isSavingEnabled } =
    useHilPreferences();

  const handleEnable = async () => {
    try {
      await setEnabled(true);
    } catch {
      toast.error("Failed to enable approvals");
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
            Approvals are off — GAIA won't ask before running these.
          </span>
          <Button
            size="sm"
            variant="flat"
            isLoading={isSavingEnabled}
            onPress={handleEnable}
          >
            Enable
          </Button>
        </div>
      )}
      <div className="divide-y divide-zinc-800/60">
        {ordered.map((tool) => {
          const ask = toolAsks(prefs, tool.name, tool.destructive);
          return (
            <div
              key={tool.name}
              className="flex items-center justify-between gap-3 py-2.5"
            >
              <div className="flex min-w-0 items-center gap-2">
                <ShieldIcon
                  width={15}
                  className={`shrink-0 ${ask ? "text-amber-400" : "text-zinc-600"}`}
                />
                <span className="truncate text-sm text-zinc-200">
                  {tool.label}
                </span>
              </div>
              <Switch
                size="sm"
                isSelected={ask}
                isDisabled={disabled}
                onValueChange={(v) =>
                  setToolApproval(tool.name, v, tool.destructive)
                }
                aria-label={`Ask before ${tool.label}`}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};
