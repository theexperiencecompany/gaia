import { Button } from "@heroui/button";
import type React from "react";
import { useIntegrationSearch } from "../hooks/useIntegrationSearch";
import { useIntegrations } from "../hooks/useIntegrations";
import { IntegrationItem } from "./IntegrationsCard";
import { IntegrationsSearchInput } from "./IntegrationsSearchInput";

export const IntegrationsList: React.FC<{
  onIntegrationClick?: (integrationId: string) => void;
}> = ({ onIntegrationClick }) => {
  const { integrations, connectIntegration } = useIntegrations();

  const { searchQuery, setSearchQuery, clearSearch, filteredIntegrations } =
    useIntegrationSearch(integrations);

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  const connectedIntegrations = filteredIntegrations.filter(
    (i) => i.status === "connected",
  );
  const availableIntegrations = filteredIntegrations.filter(
    (i) => i.status === "not_connected" && i.loginEndpoint,
  );
  const comingSoonIntegrations = filteredIntegrations.filter(
    (i) => !i.loginEndpoint,
  );

  const hasResults =
    connectedIntegrations.length > 0 ||
    availableIntegrations.length > 0 ||
    comingSoonIntegrations.length > 0;

  return (
    <div>
      <div className="mb-6 space-y-3">
        <IntegrationsSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          onClear={clearSearch}
        />
      </div>

      {!hasResults && searchQuery && (
        <div className="py-16 text-center">
          <p className="text-sm text-zinc-400">
            No integrations found for &ldquo;{searchQuery}&rdquo;
          </p>
          <Button
            onPress={clearSearch}
            variant="light"
            className="mt-2 text-zinc-400"
          >
            Clear search
          </Button>
        </div>
      )}

      {!hasResults && !searchQuery && integrations.length === 0 && (
        <div className="py-16 text-center">
          <p className="text-sm text-zinc-400">No integrations available</p>
          <p className="mt-1 text-xs text-zinc-500">
            Check back later for new integrations
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3">
        {connectedIntegrations.length > 0 &&
          connectedIntegrations.map((integration) => (
            <IntegrationItem
              key={integration.id}
              integration={integration}
              onConnect={handleConnect}
              onClick={(id) => onIntegrationClick?.(id)}
            />
          ))}

        {availableIntegrations.length > 0 &&
          availableIntegrations.map((integration) => (
            <IntegrationItem
              key={integration.id}
              integration={integration}
              onConnect={handleConnect}
              onClick={(id) => onIntegrationClick?.(id)}
            />
          ))}

        {comingSoonIntegrations.length > 0 &&
          comingSoonIntegrations.map((integration) => (
            <IntegrationItem
              key={integration.id}
              integration={integration}
              onConnect={handleConnect}
              onClick={(id) => onIntegrationClick?.(id)}
            />
          ))}
      </div>
    </div>
  );
};
