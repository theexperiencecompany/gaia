import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Plus, Puzzle } from "lucide-react";
import Image from "next/image";
import React from "react";

import { SettingsCard } from "@/features/settings/components/SettingsCard";

import { useIntegrations } from "../hooks/useIntegrations";
import { useIntegrationSearch } from "../hooks/useIntegrationSearch";
import { Integration } from "../types";
import { IntegrationsSearchInput } from "./IntegrationsSearchInput";

const IntegrationSettingsCard: React.FC<{
  integration: Integration;
  onConnect: (id: string) => void;
  onDisconnect: (id: string) => void;
}> = ({ integration, onConnect, onDisconnect: _onDisconnect }) => {
  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;

  return (
    <div className="group relative flex h-full flex-col rounded-2xl bg-zinc-800/50 p-5 transition-all hover:bg-zinc-800">
      <div className="mb-3 flex items-start justify-between">
        <div className="flex flex-shrink-0 items-center justify-center">
          <Image
            src={integration.icons[0]}
            alt={integration.name}
            width={40}
            height={40}
            className="h-7 w-7 object-contain"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
        {isConnected ? (
          <Chip variant="flat" size="sm" color="success" className="h-6">
            Connected
          </Chip>
        ) : isAvailable ? (
          <Button
            color="primary"
            size="sm"
            className="w-fit font-medium"
            onPress={() => onConnect(integration.id)}
          >
            Connect
          </Button>
        ) : (
          <Chip variant="flat" size="sm" color="warning" className="h-6">
            Soon
          </Chip>
        )}
      </div>

      <div
        className={`${isAvailable && !isConnected ? "mb-2" : "mb-0"} flex-1`}
      >
        <h3 className="mb-1 text-base font-medium text-white">
          {integration.name}
        </h3>
        <p className="text-sm leading-relaxed text-zinc-400">
          {integration.description}
        </p>
      </div>
    </div>
  );
};

export const IntegrationsSettings: React.FC = () => {
  const { integrations, connectIntegration, disconnectIntegration, isLoading } =
    useIntegrations();

  const { searchQuery, setSearchQuery, clearSearch, filteredIntegrations } =
    useIntegrationSearch(integrations);

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  const handleDisconnect = async (integrationId: string) => {
    try {
      await disconnectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to disconnect integration:", error);
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
    <SettingsCard
      title="Integrations"
      className="bg-transparent! p-0! outline-none"
    >
      <div className="mb-6 space-y-6">
        <div>
          <p className="text-[15px] leading-relaxed text-zinc-400">
            Connect your favorite apps and services to unlock powerful AI
            capabilities
          </p>
        </div>

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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {connectedIntegrations.length > 0 &&
          connectedIntegrations.map((integration) => (
            <IntegrationSettingsCard
              key={integration.id}
              integration={integration}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
            />
          ))}

        {availableIntegrations.length > 0 &&
          availableIntegrations.map((integration) => (
            <IntegrationSettingsCard
              key={integration.id}
              integration={integration}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
            />
          ))}

        {comingSoonIntegrations.length > 0 &&
          comingSoonIntegrations.map((integration) => (
            <IntegrationSettingsCard
              key={integration.id}
              integration={integration}
              onConnect={handleConnect}
              onDisconnect={handleDisconnect}
            />
          ))}
      </div>
    </SettingsCard>
  );
};
