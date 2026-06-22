import { useCallback, useMemo } from "react";
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
 * Resolves an integration id to its human-readable name / icon.
 *
 * Custom MCP integrations are surfaced by id in several backend streams
 * (tool categories, todo_progress sources), so any UI that displays one needs
 * the same id-to-name lookup. Centralised here so there is a single source of
 * truth instead of each consumer rebuilding the map from `useIntegrations`.
 */
export const useIntegrationLookup = (): UseIntegrationLookupReturn => {
  const { integrations } = useIntegrations();

  const lookup = useMemo(() => {
    const map = new Map<string, IntegrationLookupEntry>();
    for (const int of integrations) {
      if (int.id) map.set(int.id, { iconUrl: int.iconUrl, name: int.name });
    }
    return map;
  }, [integrations]);

  const getIntegrationName = useCallback(
    (integrationId: string) => lookup.get(integrationId)?.name,
    [lookup],
  );

  const getIntegrationIconUrl = useCallback(
    (integrationId: string) => lookup.get(integrationId)?.iconUrl,
    [lookup],
  );

  return { getIntegrationName, getIntegrationIconUrl };
};
