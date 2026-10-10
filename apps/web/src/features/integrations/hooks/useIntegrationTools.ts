import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { formatToolName, toTitleCase } from "@/features/chat/utils/chatUtils";

import { integrationsApi } from "../api/integrationsApi";
import { integrationKeys } from "../api/queryKeys";
import type { Integration } from "../types";
import { escapeRegExp } from "../utils/toolMentions";

export interface IntegrationToolEntry {
  name: string;
  label: string;
  destructive: boolean;
}

export interface UseIntegrationToolsReturn {
  tools: IntegrationToolEntry[];
  mentionNames: string[];
  isLoading: boolean;
}

/**
 * Tools belonging to one integration, with readable display labels
 * (formatted, category-prefix-stripped). Fetched on demand from
 * GET /integrations/{id}/tools. `mentionNames` is the deduped label list
 * driving `@` mention autocomplete in custom instructions.
 */
export const useIntegrationTools = (
  integration: Integration,
  categoryPrefix?: string,
): UseIntegrationToolsReturn => {
  const { data, isLoading } = useQuery({
    queryKey: integrationKeys.tools(integration.id),
    queryFn: () => integrationsApi.getIntegrationTools(integration.id),
  });

  const { tools, mentionNames } = useMemo(() => {
    const prefixRegex = categoryPrefix
      ? new RegExp(`^${escapeRegExp(categoryPrefix)}\\s*`, "i")
      : null;

    const entries: IntegrationToolEntry[] = (data?.tools ?? []).map((tool) => {
      const formatted = formatToolName(tool.name);
      const stripped = prefixRegex
        ? formatted.replace(prefixRegex, "").trim()
        : formatted;
      // Stripping a category prefix can leave a lowercase leading character
      // (e.g. removing "Gmail" from "Gmailsearch" yields "search"), so
      // re-apply Title Case to guarantee every word starts uppercase.
      const label = toTitleCase(stripped || formatted);
      return { name: tool.name, label, destructive: tool.destructive ?? false };
    });

    const mentionNames = Array.from(
      new Set(entries.flatMap((entry) => (entry.label ? [entry.label] : []))),
    );

    return { tools: entries, mentionNames };
  }, [data, categoryPrefix]);

  return { tools, mentionNames, isLoading };
};
