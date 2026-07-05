"use client";

import { Switch } from "@heroui/switch";
import { ShieldIcon } from "@icons";
import { useMemo } from "react";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";
import {
  toolAsks,
  useHilPreferences,
} from "@/features/settings/hooks/useHilPreferences";

interface IntegrationToolApprovalsProps {
  tools: IntegrationToolEntry[];
}

/**
 * Per-tool approval switches for a connected integration. Each switch reflects
 * `override ?? tool.destructive`; flipping it stores a diff via HIL prefs. Order
 * is fixed on the default gating (gated-first) so toggling never reorders rows.
 */
export const IntegrationToolApprovals = ({
  tools,
}: IntegrationToolApprovalsProps) => {
  const { prefs, setToolApproval } = useHilPreferences();

  const ordered = useMemo(
    () =>
      [...tools].sort((a, b) => Number(b.destructive) - Number(a.destructive)),
    [tools],
  );

  return (
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
              onValueChange={(v) =>
                setToolApproval(tool.name, v, tool.destructive)
              }
              aria-label={`Ask before ${tool.label}`}
            />
          </div>
        );
      })}
    </div>
  );
};
