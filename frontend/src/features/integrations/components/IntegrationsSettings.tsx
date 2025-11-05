import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { motion } from "framer-motion";
import { Plus, Puzzle } from "lucide-react";
import React from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { SettingsCard } from "@/features/settings/components/SettingsCard";

import { useIntegrations } from "../hooks/useIntegrations";
import { Integration } from "../types";

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
        <Chip variant="flat" size="sm" color="success">
          Connected
        </Chip>
      );
    }

    if (isAvailable) {
      return (
        <Chip variant="flat" size="sm">
          Not Connected
        </Chip>
      );
    }

    return (
      <Chip variant="flat" size="sm" color="danger">
        Coming Soon
      </Chip>
    );
  };

  const getActionButton = () => {
    if (isAvailable && !isConnected) {
      return (
        <Button
          color="primary"
          className="font-medium"
          startContent={<Plus size={19} />}
          onPress={() => onConnect(integration.id)}
        >
          Connect
        </Button>
      );
    }

    return <></>;
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

        <div className="flex h-full items-center">{getActionButton()}</div>
      </div>
    </motion.div>
  );
};

export const IntegrationsSettings: React.FC = () => {
  const { integrations, connectIntegration, disconnectIntegration, isLoading } =
    useIntegrations();

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

  const connectedIntegrations = integrations.filter(
    (i) => i.status === "connected",
  );
  const availableIntegrations = integrations.filter(
    (i) => i.status === "not_connected" && i.loginEndpoint,
  );
  const comingSoonIntegrations = integrations.filter((i) => !i.loginEndpoint);

  if (isLoading) {
    return (
      <SettingsCard
        icon={<Puzzle className="h-5 w-5 text-purple-400" />}
        title="Integrations"
      >
        <div className="flex justify-center py-12">
          <div className="text-zinc-400">Loading integrations...</div>
        </div>
      </SettingsCard>
    );
  }

  return (
    <SettingsCard title="Integrations">
      <p className="mb-6 text-sm text-zinc-400">
        Connect your favorite apps and services to unlock powerful AI
        capabilities
      </p>

      <div className="space-y-4">
        {/* Connected Integrations */}
        {connectedIntegrations.length > 0 && (
          <div className="space-y-4">
            {connectedIntegrations.map((integration) => (
              <IntegrationSettingsCard
                key={integration.id}
                integration={integration}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
              />
            ))}
          </div>
        )}

        {/* Available Integrations */}
        {availableIntegrations.length > 0 && (
          <div className="space-y-4">
            {availableIntegrations.map((integration) => (
              <IntegrationSettingsCard
                key={integration.id}
                integration={integration}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
              />
            ))}
          </div>
        )}

        {/* Coming Soon */}
        {comingSoonIntegrations.length > 0 && (
          <div className="space-y-4">
            {comingSoonIntegrations.map((integration) => (
              <IntegrationSettingsCard
                key={integration.id}
                integration={integration}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
              />
            ))}
          </div>
        )}

        {/* Empty State */}
        {integrations.length === 0 && (
          <div className="py-12 text-center">
            <div className="mb-2 text-zinc-400">No integrations available</div>
            <div className="text-sm text-zinc-500">
              Check back later for new integrations
            </div>
          </div>
        )}
      </div>
    </SettingsCard>
  );
};
