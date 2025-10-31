import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { motion } from "framer-motion";
import { Plus, Puzzle } from "lucide-react";
import Image from "next/image";
import React, { useState } from "react";

import { SettingsCard } from "@/features/settings/components/SettingsCard";

import { useIntegrations } from "../hooks/useIntegrations";
import { useMCPServers } from "../hooks/useMCPServers";
import { Integration } from "../types";
import { MCPServerTemplate } from "../api/mcpApi";
import { MCPServerDialog } from "./MCPServerDialog";

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
            <Image
              src={integration.icons[0]}
              alt={integration.name}
              width={32}
              height={32}
              className="h-8 w-8 object-contain"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
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

const MCPServerSettingsCard: React.FC<{
  template: MCPServerTemplate;
  isConfigured: boolean;
  onConfigure: (template: MCPServerTemplate) => void;
}> = ({ template, isConfigured, onConfigure }) => {
  const getStatusBadge = () => {
    if (isConfigured) {
      return (
        <Chip variant="flat" size="sm" color="success">
          Connected
        </Chip>
      );
    }
    return (
      <Chip variant="flat" size="sm">
        Not Connected
      </Chip>
    );
  };

  const getActionButton = () => {
    if (!isConfigured) {
      return (
        <Button
          color="primary"
          className="font-medium"
          startContent={<Plus size={19} />}
          onPress={() => onConfigure(template)}
        >
          Configure
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
        {/* MCP Server Info */}
        <div className="flex flex-1 items-start gap-4">
          {/* Icon */}
          <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-xl bg-zinc-700">
            <Image
              src={template.icon_url}
              alt={template.name}
              width={32}
              height={32}
              className="h-8 w-8 object-contain"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-4">
              <h3 className="text-base font-medium text-white">
                {template.name}
              </h3>
              {getStatusBadge()}
            </div>

            <p className="text-sm leading-relaxed text-zinc-500">
              {template.description}
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
  const {
    templates: mcpTemplates,
    servers: mcpServers,
    isLoading: mcpLoading,
    refreshServers,
  } = useMCPServers();
  const [selectedTemplate, setSelectedTemplate] =
    useState<MCPServerTemplate | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);

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

  const handleConfigure = (template: MCPServerTemplate) => {
    setSelectedTemplate(template);
    setIsDialogOpen(true);
  };

  const handleDialogClose = () => {
    setIsDialogOpen(false);
    setSelectedTemplate(null);
  };

  const handleServerCreated = async () => {
    await refreshServers();
    handleDialogClose();
  };

  const isTemplateConfigured = (templateId: string) => {
    return mcpServers.some(
      (server) =>
        server.name.toLowerCase().includes(templateId.toLowerCase()) ||
        server.description.toLowerCase().includes(templateId.toLowerCase()),
    );
  };

  const connectedIntegrations = integrations.filter(
    (i) => i.status === "connected",
  );
  const availableIntegrations = integrations.filter(
    (i) => i.status === "not_connected" && i.loginEndpoint,
  );
  const comingSoonIntegrations = integrations.filter((i) => !i.loginEndpoint);

  const connectedMCPServers = mcpTemplates.filter((t) =>
    isTemplateConfigured(t.id),
  );
  const availableMCPServers = mcpTemplates.filter(
    (t) => !isTemplateConfigured(t.id),
  );

  if (isLoading || mcpLoading) {
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
    <>
      <SettingsCard title="Integrations">
        <p className="mb-6 text-sm text-zinc-400">
          Connect your favorite apps and services to unlock powerful AI
          capabilities
        </p>

        <div className="space-y-6">
          {/* MCP Servers Section */}
          {mcpTemplates.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium text-zinc-300">
                  MCP Servers
                </h3>
                <Chip size="sm" variant="flat">
                  {connectedMCPServers.length}/{mcpTemplates.length}
                </Chip>
              </div>

              {/* Connected MCP Servers */}
              {connectedMCPServers.length > 0 && (
                <div className="space-y-4">
                  {connectedMCPServers.map((template) => (
                    <MCPServerSettingsCard
                      key={template.id}
                      template={template}
                      isConfigured={true}
                      onConfigure={handleConfigure}
                    />
                  ))}
                </div>
              )}

              {/* Available MCP Servers */}
              {availableMCPServers.length > 0 && (
                <div className="space-y-4">
                  {availableMCPServers.map((template) => (
                    <MCPServerSettingsCard
                      key={template.id}
                      template={template}
                      isConfigured={false}
                      onConfigure={handleConfigure}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* OAuth Integrations Section */}
          {integrations.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium text-zinc-300">
                  OAuth Integrations
                </h3>
                <Chip size="sm" variant="flat">
                  {connectedIntegrations.length}/{integrations.length}
                </Chip>
              </div>
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
            </div>
          )}

          {/* Empty State */}
          {integrations.length === 0 && mcpTemplates.length === 0 && (
            <div className="py-12 text-center">
              <div className="mb-2 text-zinc-400">
                No integrations available
              </div>
              <div className="text-sm text-zinc-500">
                Check back later for new integrations
              </div>
            </div>
          )}
        </div>
      </SettingsCard>

      {/* MCP Configuration Dialog */}
      {selectedTemplate && (
        <MCPServerDialog
          isOpen={isDialogOpen}
          onClose={handleDialogClose}
          template={selectedTemplate}
          onSuccess={handleServerCreated}
        />
      )}
    </>
  );
};
