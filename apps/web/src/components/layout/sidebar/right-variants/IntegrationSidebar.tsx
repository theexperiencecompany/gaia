"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import React, { useState } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { RaisedButton, Separator, SidebarHeader } from "@/components/ui";
import { SidebarContent } from "@/components/ui/sidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { Integration } from "@/features/integrations/types";

interface IntegrationSidebarProps {
  integration: Integration;
  onConnect: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  onDisconnect?: (integrationId: string) => void;
  category?: string;
}

export const IntegrationSidebar: React.FC<IntegrationSidebarProps> = ({
  integration,
  onConnect,
  onDisconnect,
  category,
}) => {
  const isConnected = integration.status === "connected";
  // Use backend's 'available' field - MCP integrations have available=true but loginEndpoint=null
  const isAvailable = integration.available ?? !!integration.loginEndpoint;
  const { tools } = useToolsWithIntegrations();
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  // Get tools that belong to this integration or its included integrations
  const integrationTools = React.useMemo(() => {
    const integrationIds = [
      integration.id,
      ...(integration.includedIntegrations || []),
    ].map((id) => id.toLowerCase());

    return tools.filter((tool) =>
      integrationIds.includes(
        tool.integration?.requiredIntegration.toLowerCase() || "",
      ),
    );
  }, [tools, integration.id, integration.includedIntegrations]);

  const handleConnect = async () => {
    if (!isAvailable || isConnected || isConnecting) return;

    setIsConnecting(true);
    try {
      await onConnect(integration.id);
    } catch {
      // Error toast is handled in the hook
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = () => {
    if (isConnected && onDisconnect) {
      setShowDisconnectDialog(true);
    }
  };

  const confirmDisconnect = async () => {
    if (onDisconnect) {
      setIsDisconnecting(true);
      try {
        await onDisconnect(integration.id);
      } finally {
        setIsDisconnecting(false);
        setShowDisconnectDialog(false);
      }
    }
  };

  return (
    <div className="flex h-full max-h-[calc(100vh-60px)] flex-col px-5">
      <SidebarHeader>
        <div className="w-fit">
          {getToolCategoryIcon(integration.id, {
            size: 40,
            width: 40,
            height: 40,
            showBackground: false,
          })}
        </div>

        <div className="mb-0 flex flex-col items-start gap-1">
          <div className="flex w-full items-center justify-between">
            <h1 className="text-2xl font-semibold text-zinc-100">
              {integration.name}
            </h1>

            {isConnected &&
              !(
                integration.managedBy === "mcp" &&
                integration.authType === "none"
              ) && (
                <Chip size="sm" variant="flat" color="success">
                  Connected
                </Chip>
              )}
            {!isAvailable && (
              <Chip size="sm" variant="flat" color="default">
                Coming Soon
              </Chip>
            )}
            {/* Show "Always available" for unauthenticated MCPs */}
            {integration.managedBy === "mcp" &&
              integration.authType === "none" && (
                <Chip size="sm" variant="flat" color="secondary">
                  Always available
                </Chip>
              )}
          </div>

          <p className="text-sm leading-relaxed font-light text-zinc-400">
            {integration.description}
          </p>
        </div>

        {/* Hide connect/disconnect for unauthenticated MCPs */}
        {integration.managedBy === "mcp" && integration.authType === "none" ? (
          <div className="text-sm text-zinc-400">
            This integration is always available - no connection needed.
          </div>
        ) : !isConnected ? (
          <RaisedButton
            color="#00bbff"
            className="font-medium text-black!"
            onClick={handleConnect}
            disabled={!isAvailable || isConnecting}
            isLoading={isConnecting}
          >
            {isConnecting
              ? "Connecting..."
              : isAvailable
                ? "Connect"
                : "Coming Soon"}
          </RaisedButton>
        ) : (
          onDisconnect && (
            <Button
              color="danger"
              variant="light"
              fullWidth
              onPress={handleDisconnect}
              isLoading={isDisconnecting}
              isDisabled={isDisconnecting}
            >
              Disconnect
            </Button>
          )
        )}
        {integrationTools.length > 0 && (
          <>
            <Separator className="my-3 bg-zinc-800" />
            <h2 className="mb-2 text-sm font-medium text-zinc-300">
              Available Tools ({integrationTools.length})
            </h2>
          </>
        )}
      </SidebarHeader>
      <SidebarContent className="flex-1 overflow-y-auto">
        <div className="space-y-4 pb-4">
          {integrationTools.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {integrationTools.map((tool) => (
                <Chip
                  key={tool.name}
                  variant="bordered"
                  color="default"
                  radius="full"
                  className="font-light border-1 text-zinc-300"
                >
                  {category
                    ? formatToolName(tool.name)
                        .replace(new RegExp(`^${category}\\s*`, "gi"), "")
                        .trim()
                    : formatToolName(tool.name)}
                </Chip>
              ))}
            </div>
          )}
        </div>
      </SidebarContent>

      <ConfirmationDialog
        isOpen={showDisconnectDialog}
        title="Disconnect Integration"
        message={`Are you sure you want to disconnect ${integration.name}? This will revoke access and you'll need to reconnect to use this integration again.`}
        confirmText="Disconnect"
        cancelText="Cancel"
        variant="destructive"
        onConfirm={confirmDisconnect}
        onCancel={() => setShowDisconnectDialog(false)}
      />
    </div>
  );
};
