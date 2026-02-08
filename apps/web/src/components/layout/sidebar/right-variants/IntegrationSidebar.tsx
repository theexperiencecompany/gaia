"use client";

import { Avatar } from "@heroui/avatar";
import { Button, ButtonGroup } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import React, { useState } from "react";
import { toast } from "sonner";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { RaisedButton, SidebarHeader } from "@/components/ui";
import { SidebarContent } from "@/components/ui/sidebar";
import { useToolsWithIntegrations } from "@/features/chat/hooks/useToolsWithIntegrations";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import type { Integration } from "@/features/integrations/types";
import {
  GlobalIcon,
  LinkSquareIcon,
  RemoveCircleIcon,
  Share08Icon,
  Unlink04Icon,
  UserCircle02Icon,
} from "@/icons";
import { useUserStore } from "@/stores/userStore";

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
  const showRetry = integration.status === "created";
  const { tools } = useToolsWithIntegrations();
  const queryClient = useQueryClient();

  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [showBearerModal, setShowBearerModal] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);

  const currentUserId = useUserStore((state) => state.userId);
  const currentUserName = useUserStore((state) => state.name);
  const currentUserPicture = useUserStore((state) => state.profilePicture);

  // Determine if this is a custom integration created by the current user
  const isOwnIntegration = React.useMemo(() => {
    if (integration.source !== "custom") return false;
    if (!integration.createdBy) return false;
    return integration.createdBy === currentUserId;
  }, [integration.source, integration.createdBy, currentUserId]);

  // Determine if this is a forked integration (added from marketplace, created by someone else)
  const isForkedIntegration = React.useMemo(() => {
    if (integration.source !== "custom") return false;
    if (!integration.createdBy) return false;
    return integration.createdBy !== currentUserId;
  }, [integration.source, integration.createdBy, currentUserId]);

  // Show delete/remove button for non-connected custom integrations
  const showDeleteButton =
    !isConnected && integration.source === "custom" && onDelete;

  // Calculate how many buttons will be shown to determine icon-only mode
  const buttonCount = [
    !!onDisconnect,
    integration.isPublic, // View on Marketplace
    isOwnIntegration && integration.isPublic, // Unpublish
    isOwnIntegration && !integration.isPublic, // Publish
    integration.isPublic, // Share
  ].filter(Boolean).length;

  const useIconOnly = buttonCount >= 3;

  // Get tools that belong to this integration
  const integrationTools = React.useMemo(() => {
    const integrationIds = [
      integration.id,
      ...(integration.includedIntegrations || []),
    ].map((id) => id.toLowerCase());

    return tools.filter((tool) =>
      integrationIds.includes(tool.category.toLowerCase()),
    );
  }, [tools, integration.id, integration.includedIntegrations]);

  const handleConnect = async () => {
    if (isConnected || isConnecting) return;

    // For bearer-auth integrations, show modal instead of direct connect
    if (integration.authType === "bearer" && integration.requiresAuth) {
      setShowBearerModal(true);
      return;
    }

    setIsConnecting(true);
    try {
      await onConnect(integration.id);
    } catch {
      // Error toast is handled in the hook
    } finally {
      setIsConnecting(false);
    }
  };

  const handleBearerSubmit = async (_id: string, token: string) => {
    const toastId = toast.loading(`Connecting to ${integration.name}...`);
    try {
      const result = await integrationsApi.connectIntegration(
        integration.id,
        token,
      );
      if (result.status === "connected") {
        toast.success(`Connected to ${integration.name}`, { id: toastId });
        // Refetch all data to update sidebar
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["integrations"] }),
          queryClient.invalidateQueries({ queryKey: ["tools", "available"] }),
          queryClient.invalidateQueries({ queryKey: ["tools"] }),
        ]);
      } else {
        toast.error(`Connection failed: ${result.status}`, { id: toastId });
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Connection failed",
        { id: toastId },
      );
      throw error;
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

  const handlePublish = () => {
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
        toast.error("Unable to publish: handler not available");
      }
    } catch {
      // Error toast is handled in the hook
    } finally {
      setIsPublishing(false);
      setShowPublishDialog(false);
    }
  };

  // Dynamic text based on ownership
  const deleteButtonText = isForkedIntegration
    ? "Remove from GAIA"
    : "Delete Integration";
  const deleteDialogTitle = isForkedIntegration
    ? "Remove Integration"
    : "Delete Integration";
  const deleteDialogMessage = isForkedIntegration
    ? `Are you sure you want to remove ${integration.name} from your GAIA? You can add it again from the marketplace.`
    : `Are you sure you want to delete ${integration.name}? This action cannot be undone.`;
  const deleteDialogConfirmText = isForkedIntegration ? "Remove" : "Delete";

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
          <div className="flex items-center gap-2 flex-row mb-2">
            {isConnected && (
              <Chip size="sm" variant="flat" color="success" radius="sm">
                Connected
              </Chip>
            )}
            {integration.source === "custom" && (
              <div className="flex items-center gap-1">
                {isForkedIntegration && integration.creator && (
                  <Chip
                    size="sm"
                    variant="flat"
                    radius="sm"
                    className="text-xs font-light relative text-foreground-500"
                    startContent={
                      integration.creator.picture ? (
                        <Avatar
                          src={integration.creator.picture || undefined}
                          name={integration.creator.name || undefined}
                          size="sm"
                          className="h-4 w-4"
                        />
                      ) : (
                        <UserCircle02Icon width={16} height={16} />
                      )
                    }
                  >
                    <div className="flex items-center gap-1.5 text-xs pl-0.5">
                      <span>
                        Created by {integration.creator.name || "Unknown"}
                      </span>
                    </div>
                  </Chip>
                )}
                {isOwnIntegration && (
                  <Chip
                    size="sm"
                    variant="flat"
                    color="default"
                    radius="sm"
                    className="text-xs text-zinc-400 font-light relative right-1"
                    startContent={
                      <Avatar
                        src={currentUserPicture || undefined}
                        name={currentUserName || undefined}
                        size="sm"
                        className="h-4 w-4"
                      />
                    }
                  >
                    Created by You
                  </Chip>
                )}
              </div>
            )}
          </div>

          <h1 className="text-2xl font-semibold text-zinc-100">
            {integration.name}
          </h1>

          <p className="text-sm leading-relaxed font-light text-zinc-400">
            {integration.description}
          </p>
        </div>
        {/* Connect/Disconnect buttons */}
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

            {integration.isPublic && (
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

            {isOwnIntegration && integration.isPublic && (
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

            {isOwnIntegration && !integration.isPublic && (
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

            {integration.isPublic && (
              <Tooltip content="Copy share link to clipboard">
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  color="default"
                  onPress={async () => {
                    try {
                      await navigator.clipboard.writeText(
                        `${window.location.origin}/marketplace/${integration.slug}`,
                      );
                      toast.success("Link copied to clipboard!");
                    } catch {
                      toast.error("Failed to copy link to clipboard");
                    }
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
        {/* Delete/Remove button for non-connected custom integrations */}
        {showDeleteButton && (
          <Button
            color="danger"
            variant="light"
            fullWidth
            onPress={handleDelete}
            isLoading={isDeleting}
            isDisabled={isDeleting}
          >
            {deleteButtonText}
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
        isLoading={isDisconnecting}
        onConfirm={confirmDisconnect}
        onCancel={() => setShowDisconnectDialog(false)}
      />

      <ConfirmationDialog
        isOpen={showDeleteDialog}
        title={deleteDialogTitle}
        message={deleteDialogMessage}
        confirmText={deleteDialogConfirmText}
        cancelText="Cancel"
        variant="destructive"
        isLoading={isDeleting}
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
        isLoading={isPublishing}
        onConfirm={confirmPublish}
        onCancel={() => setShowPublishDialog(false)}
      />

      <BearerTokenModal
        isOpen={showBearerModal}
        onClose={() => setShowBearerModal(false)}
        integrationId={integration.id}
        integrationName={integration.name}
        onSubmit={handleBearerSubmit}
      />
    </div>
  );
};
