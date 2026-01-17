"use client";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { RaisedButton, SidebarHeader } from "@/components/ui";
import { SidebarContent } from "@/components/ui/sidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { Integration } from "@/features/integrations/types";
import {
  GlobalIcon,
  LinkSquareIcon,
  RemoveCircleIcon,
  Share08Icon,
  Unlink04Icon,
} from "@/icons";
import { Button, ButtonGroup } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import Link from "next/link";
import React, { useState } from "react";
import { toast } from "sonner";

interface IntegrationSidebarProps {
  integration: Integration;
  onConnect: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  onDisconnect?: (integrationId: string) => void;
  onDelete?: (integrationId: string) => Promise<void>;
  onPublish?: (integrationId: string) => Promise<void>;
  onUnpublish?: (integrationId: string) => Promise<void>;
  category?: string;
}

export const IntegrationSidebar: React.FC<IntegrationSidebarProps> = ({
  integration,
  onConnect,
  onDisconnect,
  onDelete,
  onPublish,
  onUnpublish,
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
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);

  // Calculate how many buttons will be shown to determine icon-only mode
  const buttonCount = [
    !!onDisconnect,
    integration.isPublic && integration.slug, // View on Marketplace
    integration.source === "custom" && integration.isPublic, // Unpublish
    integration.source === "custom" && !integration.isPublic, // Publish
    integration.isPublic && integration.slug, // Share
  ].filter(Boolean).length;

  const useIconOnly = buttonCount >= 2;

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

  const handlePublish = async () => {
    if (isPublishing) return;
    setShowPublishDialog(true);
  };

  const confirmPublish = async () => {
    setIsPublishing(true);
    try {
      if (integration.isPublic && onUnpublish) {
        await onUnpublish(integration.id);
      } else if (!integration.isPublic && onPublish) {
        await onPublish(integration.id);
      } else {
        // Neither condition matched - this shouldn't happen for custom integrations
        console.error(
          "[IntegrationSidebar] confirmPublish failed: handler not available",
          {
            isPublic: integration.isPublic,
            hasOnPublish: !!onPublish,
            hasOnUnpublish: !!onUnpublish,
            source: integration.source,
          },
        );
        toast.error("Unable to publish: handler not available");
      }
    } catch (error) {
      // Error toast is handled in the hook
    } finally {
      setIsPublishing(false);
      setShowPublishDialog(false);
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
              className="mb-2 text-xs text-zinc-400 font-light relative right-1"
            >
              Created by You
            </Chip>
          )}
          <div className="flex w-full items-center justify-between">
            <h1 className="text-2xl font-semibold text-zinc-100">
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

          <p className="text-sm leading-relaxed font-light text-zinc-400">
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
          <ButtonGroup variant="flat" className="w-full" fullWidth>
            {onDisconnect && (
              <Tooltip content="Disconnect this integration">
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  color="danger"
                  onPress={handleDisconnect}
                  isLoading={isDisconnecting}
                  isDisabled={isDisconnecting}
                  aria-label="Disconnect"
                  startContent={
                    !isDisconnecting ? (
                      <Unlink04Icon
                        width={18}
                        height={18}
                        className="outline-0!"
                      />
                    ) : undefined
                  }
                >
                  {!useIconOnly && "Disconnect"}
                </Button>
              </Tooltip>
            )}

            {integration.isPublic && integration.slug && (
              <Tooltip content="View on Marketplace">
                <Button
                  className="w-full"
                  isIconOnly={useIconOnly}
                  as={Link}
                  href={`/marketplace/${integration.slug}`}
                  color="primary"
                  aria-label="View on Marketplace"
                  startContent={
                    <LinkSquareIcon
                      width={18}
                      height={18}
                      className="outline-none!"
                    />
                  }
                >
                  {!useIconOnly && "View"}
                </Button>
              </Tooltip>
            )}

            {integration.source === "custom" && integration.isPublic && (
              <Tooltip content="Unpublish from Marketplace">
                <Button
                  isIconOnly={useIconOnly}
                  color="warning"
                  className="w-full"
                  onPress={handlePublish}
                  isLoading={isPublishing}
                  isDisabled={isPublishing}
                  aria-label="Unpublish"
                  startContent={
                    !isPublishing ? (
                      <RemoveCircleIcon
                        width={18}
                        height={18}
                        className="outline-none!"
                      />
                    ) : undefined
                  }
                >
                  {!useIconOnly && "Unpublish"}
                </Button>
              </Tooltip>
            )}

            {integration.source === "custom" && !integration.isPublic && (
              <Tooltip content="Publish to Community Marketplace">
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  color="primary"
                  onPress={handlePublish}
                  isLoading={isPublishing}
                  isDisabled={isPublishing}
                  aria-label="Publish"
                  startContent={
                    !isPublishing ? (
                      <GlobalIcon width={18} height={18} />
                    ) : undefined
                  }
                >
                  {!useIconOnly && "Publish"}
                </Button>
              </Tooltip>
            )}

            {integration.isPublic && integration.slug && (
              <Tooltip content="Copy share link to clipboard">
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  color="default"
                  onPress={() => {
                    navigator.clipboard.writeText(
                      `${window.location.origin}/marketplace/${integration.slug}`,
                    );
                    toast.success("Link copied to clipboard!");
                  }}
                  aria-label="Share"
                  startContent={<Share08Icon width={18} height={18} />}
                >
                  {!useIconOnly && "Share"}
                </Button>
              </Tooltip>
            )}
          </ButtonGroup>
        )}

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
          <h2 className="mb-1 mt-3 text-xs font-medium text-zinc-400 -ml-1">
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

      <ConfirmationDialog
        isOpen={showPublishDialog}
        title={
          integration.isPublic ? "Unpublish Integration" : "Publish Integration"
        }
        message={
          integration.isPublic
            ? `Are you sure you want to unpublish ${integration.name}? It will no longer be visible in the community marketplace.`
            : `Are you sure you want to publish ${integration.name} to the community marketplace? Your integration name, description, and tool list will be publicly visible.`
        }
        confirmText={integration.isPublic ? "Unpublish" : "Publish"}
        cancelText="Cancel"
        variant={integration.isPublic ? "destructive" : "default"}
        onConfirm={confirmPublish}
        onCancel={() => setShowPublishDialog(false)}
      />
    </div>
  );
};
