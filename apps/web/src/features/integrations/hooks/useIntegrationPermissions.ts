"use client";

import { type HilMode, toolAsks } from "@shared/chat";
import { useCallback, useMemo, useState } from "react";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";
import { useHilPreferences } from "@/features/settings/hooks/useHilPreferences";
import { toast } from "@/lib/toast";

export interface IntegrationPermissions {
  mode: HilMode;
  changeMode: (mode: HilMode) => Promise<void>;
  isSavingMode: boolean;
  /** Whether a given tool currently pauses for approval. */
  asks: (tool: IntegrationToolEntry) => boolean;
  /** How many of this integration's tools are in the gated set. */
  askCount: number;
  toggle: (tool: IntegrationToolEntry, next: boolean) => void;
  /** Tools whose saved setting deviates from GAIA's recommendation. */
  deviations: number;
  resetToDefaults: () => void;
  isSavingTools: boolean;
}

/**
 * One integration's approval settings, read from and written straight to the
 * shared HIL preferences. There is no local mirror of the saved state: the
 * global mode is the only decision, and the per-tool switches are its
 * exceptions.
 */
export function useIntegrationPermissions(
  tools: IntegrationToolEntry[],
): IntegrationPermissions {
  const {
    prefs,
    mode,
    setMode,
    isSavingMode,
    isSavingTools,
    setToolApproval,
    setToolApprovals,
  } = useHilPreferences();

  const asks = useCallback(
    (tool: IntegrationToolEntry) =>
      toolAsks(prefs, tool.name, tool.destructive),
    [prefs],
  );

  // A tool's recommendation is its `destructive` classification, so anything
  // that no longer matches it is a choice the user made by hand.
  const deviating = useMemo(
    () => tools.filter((tool) => asks(tool) !== tool.destructive),
    [tools, asks],
  );

  return {
    mode,
    changeMode: async (next) => {
      try {
        await setMode(next);
      } catch {
        toast.error("Failed to update approval mode");
      }
    },
    isSavingMode,
    asks,
    // Wrapped rather than passed by reference: filter also hands the callback an
    // index and the array, which would silently become extra arguments.
    askCount: useMemo(
      () => tools.filter((tool) => asks(tool)).length,
      [tools, asks],
    ),
    toggle: (tool, next) => setToolApproval(tool.name, next, tool.destructive),
    deviations: deviating.length,
    resetToDefaults: () =>
      setToolApprovals(
        deviating.map((tool) => ({
          name: tool.name,
          ask: tool.destructive,
          destructive: tool.destructive,
        })),
      ),
    isSavingTools,
  };
}

export interface ToolFilter {
  query: string;
  setQuery: (value: string) => void;
  visible: IntegrationToolEntry[];
}

/** Text filter over a tool list, matching the display label. */
export function useToolFilter(tools: IntegrationToolEntry[]): ToolFilter {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return tools;
    return tools.filter((tool) => tool.label.toLowerCase().includes(q));
  }, [tools, query]);
  return { query, setQuery, visible };
}
