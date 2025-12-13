import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import type React from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationSearch } from "../hooks/useIntegrationSearch";
import { useIntegrations } from "../hooks/useIntegrations";
import type { Integration } from "../types";
import { IntegrationsSearchInput } from "./IntegrationsSearchInput";

const IntegrationRow: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
  onClick: (id: string) => void;
}> = ({ integration, onConnect, onClick }) => {
  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;

  const handleClick = () => {
    onClick(integration.id);
  };

  return (
    <div
      className="flex min-h-16 cursor-pointer items-center gap-4 overflow-hidden rounded-xl bg-zinc-800/40 px-4 py-3 transition hover:bg-zinc-700"
      onClick={handleClick}
    >
      <div className="flex-shrink-0">
        {getToolCategoryIcon(integration.id, {
          size: 32,
          width: 32,
          height: 32,
          showBackground: false,
        })}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="text-sm font-medium">{integration.name}</div>
        <div className="truncate text-xs font-light text-zinc-400">
          {integration.description}
        </div>
      </div>

      <div className="flex-shrink-0">
        {isConnected && (
          <Chip size="sm" variant="flat" color="success">
            Connected
          </Chip>
        )}

        {isAvailable && !isConnected && (
          <Button
            size="sm"
            variant="flat"
            color="primary"
            className="text-xs text-primary"
            onPress={() => {
              onConnect(integration.id);
            }}
          >
            Connect
          </Button>
        )}

        {!isAvailable && (
          <Chip size="sm" variant="flat" color="default" className="text-xs">
            Soon
          </Chip>
        )}
      </div>
    </div>
  );
};

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

  // Separate featured integrations
  const featuredIntegrations = filteredIntegrations.filter(
    (i) => i.isFeatured && i.loginEndpoint,
  );

  // Regular integrations (non-featured)
  const connectedIntegrations = filteredIntegrations.filter(
    (i) => !i.isFeatured && i.status === "connected",
  );
  const availableIntegrations = filteredIntegrations.filter(
    (i) => !i.isFeatured && i.status === "not_connected" && i.loginEndpoint,
  );
  const comingSoonIntegrations = filteredIntegrations.filter(
    (i) => !i.loginEndpoint,
  );

  const hasResults =
    featuredIntegrations.length > 0 ||
    connectedIntegrations.length > 0 ||
    availableIntegrations.length > 0 ||
    comingSoonIntegrations.length > 0;

  return (
    <div>
      <div className="mb-6 space-y-3 flex justify-end">
        <IntegrationsSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          onClear={clearSearch}
        />
      </div>

      {!hasResults && searchQuery && (
        <div className="py-16 text-center space-y-2">
          <p className="text-sm text-zinc-400">
            No integrations found for &ldquo;{searchQuery}&rdquo;
          </p>
          <Button
            onPress={clearSearch}
            variant="light"
            color="primary"
            size="sm"
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

      {/* Featured Integrations Section */}
      {featuredIntegrations.length > 0 && (
        <div className="mb-8">
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-base font-semibold">Featured Integrations</h2>
            <Chip size="sm" variant="flat" color="primary">
              {featuredIntegrations.length}
            </Chip>
          </div>
          <div className="flex flex-col gap-2">
            {featuredIntegrations.map((integration) => (
              <IntegrationRow
                key={integration.id}
                integration={integration}
                onConnect={handleConnect}
                onClick={(id) => onIntegrationClick?.(id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* All Integrations Section */}
      {(connectedIntegrations.length > 0 ||
        availableIntegrations.length > 0 ||
        comingSoonIntegrations.length > 0) && (
        <div>
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-base font-semibold">All Integrations</h2>
            <Chip size="sm" variant="flat" color="default">
              {connectedIntegrations.length +
                availableIntegrations.length +
                comingSoonIntegrations.length}
            </Chip>
          </div>
          <div className="flex flex-col gap-2">
            {connectedIntegrations.length > 0 &&
              connectedIntegrations.map((integration) => (
                <IntegrationRow
                  key={integration.id}
                  integration={integration}
                  onConnect={handleConnect}
                  onClick={(id) => onIntegrationClick?.(id)}
                />
              ))}

            {availableIntegrations.length > 0 &&
              availableIntegrations.map((integration) => (
                <IntegrationRow
                  key={integration.id}
                  integration={integration}
                  onConnect={handleConnect}
                  onClick={(id) => onIntegrationClick?.(id)}
                />
              ))}

            {comingSoonIntegrations.length > 0 &&
              comingSoonIntegrations.map((integration) => (
                <IntegrationRow
                  key={integration.id}
                  integration={integration}
                  onConnect={handleConnect}
                  onClick={(id) => onIntegrationClick?.(id)}
                />
              ))}
          </div>
        </div>
      )}
    </div>
  );
};
