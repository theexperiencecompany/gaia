import { useCallback, useMemo } from "react";
import { normalizeCategoryName } from "@/config/toolIconConfig";
import { useIntegrations } from "./useIntegrations";

interface IntegrationLookupEntry {
  iconUrl?: string;
  name?: string;
}

export interface UseIntegrationLookupReturn {
  /** Resolve an integration id (e.g. a custom MCP id) to its display name. */
  getIntegrationName: (integrationId: string) => string | undefined;
  /** Resolve an integration id to its icon URL. */
  getIntegrationIconUrl: (integrationId: string) => string | undefined;
}

/**
 * Resolves an integration id or registry category to its name / icon.
 *
 * Ids match as categories do (normalizeCategoryName), so a workflow step's
 * Composio category ("ATTIO") finds its integration ("attio").
 */
export const useIntegrationLookup = (): UseIntegrationLookupReturn => {
  const { integrations } = useIntegrations();

  const lookup = useMemo(() => {
    const map = new Map<string, IntegrationLookupEntry>();
    for (const int of integrations) {
      if (int.id)
        map.set(normalizeCategoryName(int.id), {
          iconUrl: int.iconUrl,
          name: int.name,
        });
    }
    return map;
  }, [integrations]);

  const getIntegrationName = useCallback(
    (integrationId: string) =>
      lookup.get(normalizeCategoryName(integrationId))?.name,
    [lookup],
  );

  const getIntegrationIconUrl = useCallback(
    (integrationId: string) =>
      lookup.get(normalizeCategoryName(integrationId))?.iconUrl,
    [lookup],
  );

  return { getIntegrationName, getIntegrationIconUrl };
};
