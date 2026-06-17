import { useMemo } from "react";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { formatToolName, toTitleCase } from "@/features/chat/utils/chatUtils";

import type { Integration } from "../types";
import { escapeRegExp } from "../utils/toolMentions";

export interface IntegrationToolEntry {
  name: string;
  label: string;
}

export interface UseIntegrationToolsReturn {
  tools: IntegrationToolEntry[];
  mentionNames: string[];
}

/**
 * Tools belonging to one integration, with readable display labels
 * (formatted, category-prefix-stripped). `mentionNames` is the deduped label
 * list driving `@` mention autocomplete in custom instructions.
 */
export const useIntegrationTools = (
  integration: Integration,
  categoryPrefix?: string,
): UseIntegrationToolsReturn => {
  const { tools } = useToolsWithIntegrations();

  return useMemo(() => {
    const prefixRegex = categoryPrefix
      ? new RegExp(`^${escapeRegExp(categoryPrefix)}\\s*`, "i")
      : null;

    const integrationIds = [
      integration.id,
      ...(integration.includedIntegrations || []),
    ].map((id) => id.toLowerCase());

    const fromToolsEndpoint = tools.filter((tool) =>
      integrationIds.includes(tool.category.toLowerCase()),
    );

    // Fallback: if the /tools endpoint doesn't know about this integration's
    // tools yet, use the tools array from the integration record itself.
    const names =
      fromToolsEndpoint.length > 0
        ? fromToolsEndpoint.map((tool) => tool.name)
        : (integration.tools ?? []).map((tool) => tool.name);

    const entries: IntegrationToolEntry[] = names.map((name) => {
      const formatted = formatToolName(name);
      const stripped = prefixRegex
        ? formatted.replace(prefixRegex, "").trim()
        : formatted;
      // Stripping a category prefix can leave a lowercase leading character
      // (e.g. removing "Gmail" from "Gmailsearch" yields "search"), so
      // re-apply Title Case to guarantee every word starts uppercase.
      const label = toTitleCase(stripped || formatted);
      return { name, label };
    });

    const mentionNames = Array.from(
      new Set(entries.map((entry) => entry.label).filter(Boolean)),
    );

    return { tools: entries, mentionNames };
  }, [
    tools,
    integration.id,
    integration.includedIntegrations,
    integration.tools,
    categoryPrefix,
  ]);
};
