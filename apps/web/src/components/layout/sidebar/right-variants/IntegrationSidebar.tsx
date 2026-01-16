"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import React, { useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { RaisedButton, SidebarHeader } from "@/components/ui";
import { SidebarContent } from "@/components/ui/sidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { Integration } from "@/features/integrations/types";
import { Unlink04Icon } from "@/icons";

interface IntegrationSidebarProps {
  integration: Integration;
  onConnect: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  onDisconnect?: (integrationId: string) => void;
  onDelete?: (integrationId: string) => Promise<void>;
  category?: string;
}

export const IntegrationSidebar: React.FC<IntegrationSidebarProps> = ({
  integration,
  onConnect,
  onDisconnect,
  onDelete,
  category,
}) => {
  const isConnected = integration.status === "connected";
  // Show retry only if OAuth was started but not completed (status = "created")
  const showRetry = integration.status === "created";
  // Custom integrations are always available, platform integrations use available field
  const isAvailable = integration.source === "custom" || integration.available;
  const { tools } = useToolsWithIntegrations();
  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  // Get tools that belong to this integration
  // Priority: Use embedded tools from integration response (source of truth from MongoDB)
  // Fallback: Use global tools registry for platform integrations without embedded tools
  const integrationTools = React.useMemo(() => {
    // If integration has embedded tools (stored in MongoDB integrations.tools), use them directly
    // This is the source of truth for custom integrations and any integration with stored tools
    if (integration.tools?.length) {
      return integration.tools.map((t) => ({
        name: t.name,
        category: integration.category || "custom",
        integration: {
          toolName: t.name,
          category: integration.category || "custom",
          requiredIntegration: integration.id.toLowerCase(),
          integrationName: integration.name,
          iconUrl: integration.iconUrl,
          isRequired: true,
        },
        isLocked: false, // Connected integration tools are never locked
      }));
    }

    // Fallback to global tools registry for platform integrations without embedded tools
    const integrationIds = [
      integration.id,
      ...(integration.includedIntegrations || []),
    ].map((id) => id.toLowerCase());

    return tools.filter((tool) =>
      integrationIds.includes(
        tool.integration?.requiredIntegration.toLowerCase() || "",
      ),
    );
  }, [tools, integration]);

  const handleConnect = async () => {
    if (isConnected || isConnecting) return;

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

  const handleDelete = () => {
    if (onDelete) {
      setShowDeleteDialog(true);
    }
  };

  const confirmDelete = async () => {
    if (onDelete) {
      setIsDeleting(true);
      try {
        await onDelete(integration.id);
      } finally {
        setIsDeleting(false);
        setShowDeleteDialog(false);
      }
    }
  };

  return (
    <div className="flex h-full max-h-[calc(100vh-60px)] flex-col px-5">
      <SidebarHeader>
        <div className="w-fit">
          {getToolCategoryIcon(
            integration.id,
            {
              size: 40,
              width: 40,
              height: 40,
              showBackground: false,
            },
            integration.iconUrl,
          )}
        </div>

        <div className="mb-0 mt-2 flex flex-col items-start gap-1">
          {integration.createdBy && (
            <Chip
              size="sm"
              variant="flat"
              color="default"
              radius="sm"
              className="mb-2 text-xs text-foreground-400 font-light relative right-1"
            >
              Created by You
            </Chip>
          )}
          <div className="flex w-full items-center justify-between">
            <h1 className="text-2xl font-semibold text-foreground-900">
              {integration.name}
            </h1>

            <div className="flex items-end gap-1">
              {isConnected && (
                <Chip size="sm" variant="flat" color="success">
                  Connected
                </Chip>
              )}
            </div>
          </div>

          <p className="text-sm leading-relaxed font-light text-foreground-400">
            {integration.description}
          </p>
        </div>

        {/* Connect/Disconnect buttons for all integrations */}
        {!isConnected ? (
          <RaisedButton
            color="#00bbff"
            className="font-medium text-black!"
            onClick={handleConnect}
            disabled={isConnecting}
          >
            {isConnecting
              ? "Connecting..."
              : showRetry
                ? "Retry Connection"
                : "Connect"}
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
              endContent={
                <Unlink04Icon width={20} height={20} className="outline-0!" />
              }
            >
              Disconnect
            </Button>
          )
        )}

        {/* Delete button for integrations with status=created */}
        {showRetry && onDelete && (
          <Button
            color="danger"
            variant="light"
            fullWidth
            onPress={handleDelete}
            isLoading={isDeleting}
            isDisabled={isDeleting}
          >
            Delete Integration
          </Button>
        )}
        {integrationTools.length > 0 && (
          <h2 className="mb-1 mt-3 text-xs font-medium text-foreground-400 -ml-1">
            Available Tools ({integrationTools.length})
          </h2>
        )}
      </SidebarHeader>
      <SidebarContent className="flex-1 overflow-y-auto">
        <div className="space-y-4 pb-4">
          {integrationTools.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {integrationTools.map((tool) => (
                <Chip
                  key={tool.name}
                  variant="flat"
                  color="default"
                  radius="full"
                  className="font-light text-foreground-700"
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

      <ConfirmationDialog
        isOpen={showDeleteDialog}
        title="Delete Integration"
        message={`Are you sure you want to delete ${integration.name}? This action cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        variant="destructive"
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteDialog(false)}
      />
    </div>
  );
};
