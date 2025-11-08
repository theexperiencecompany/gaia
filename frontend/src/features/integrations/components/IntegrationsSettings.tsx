import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { motion } from "framer-motion";
import React from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
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

  const getStatusBadge = () => {
    if (isConnected) {
      return (
        <Chip variant="flat" size="sm" color="success" className="h-6">
          Connected
        </Chip>
      );
    }
    if (isAvailable) {
      return null; // Button will be shown instead
    }
    return (
      <Chip variant="flat" size="sm" color="warning" className="h-6">
        Soon
      </Chip>
    );
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl bg-zinc-800/60 p-4"
    >
      <div className="flex items-start justify-between gap-4">
        {/* Integration Info */}
        <div className="flex flex-1 items-start gap-4">
          {/* Icon */}
          <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-zinc-700">
            {getToolCategoryIcon(integration.id, {
              size: 32,
              width: 32,
              height: 32,
              showBackground: false,
            })}
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-4">
              <h3 className="text-base font-medium text-white">
                {integration.name}
              </h3>
              {getStatusBadge()}
            </div>

            <p className="text-sm leading-relaxed text-zinc-500">
              {integration.description}
            </p>
          </div>
        </div>

        {/* Action Button */}
        <div className="flex-shrink-0">
          {isAvailable && !isConnected && (
            <Button
              color="primary"
              size="sm"
              className="w-fit font-medium"
              onPress={() => onConnect(integration.id)}
            >
              Connect
            </Button>
          )}
        </div>
      </div>
    </motion.div>
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
