"use client";

import { Avatar } from "@heroui/avatar";
import { Button, ButtonGroup } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import {
  ConnectIcon,
  GlobalIcon,
  LinkSquareIcon,
  RedoIcon,
  RemoveCircleIcon,
  Share08Icon,
  Unlink04Icon,
  UserCircle02Icon,
} from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import React, { useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { RaisedButton } from "@/components/ui/raised-button";
import { SidebarContent, SidebarHeader } from "@/components/ui/sidebar";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { IntegrationInstructionsEditor } from "@/features/integrations/components/IntegrationInstructionsEditor";
import { IntegrationRelatedWorkflows } from "@/features/integrations/components/IntegrationRelatedWorkflows";
import { useIntegrationTools } from "@/features/integrations/hooks/useIntegrationTools";
import type { Integration } from "@/features/integrations/types";
import { toast } from "@/lib/toast";
import { useUserStore } from "@/stores/userStore";

// Placeholder chip widths shown while a just-connected integration's tools are
// still being discovered in the background. Distinct values double as React keys.
const SETTLING_SKELETON_WIDTHS = [
  "w-24",
  "w-20",
  "w-28",
  "w-16",
  "w-32",
  "w-14",
];

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
  /** True while a just-finished connect is still discovering tools in the background. */
  isSettling?: boolean;
}

export const IntegrationSidebar: React.FC<IntegrationSidebarProps> = ({
  integration,
  onConnect,
  onDisconnect,
  onDelete,
  onPublish,
  onUnpublish,
  category,
  isSettling = false,
}) => {
  const isConnected = integration.status === "connected";
  const showRetry = integration.status === "created";
  const queryClient = useQueryClient();

  const { tools: integrationTools, mentionNames: toolMentionNames } =
    useIntegrationTools(integration, category);

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

  // For custom integrations "Disconnect" actually removes them — deleting the
  // integration outright if you created it, or removing it from your workspace
  // if you added it from the marketplace. Word the action honestly per case.
  const isCustom = integration.source === "custom";
  const disconnectLabel = isCustom ? "Remove" : "Disconnect";
  const disconnectDialogTitle = isCustom
    ? "Remove Integration"
    : "Disconnect Integration";
  const disconnectDialogMessage = isCustom
    ? isOwnIntegration
      ? `Remove ${integration.name}? This permanently deletes the integration and its tools, and can't be undone.`
      : `Remove ${integration.name} from your workspace? You can add it again from the marketplace later.`
    : `Are you sure you want to disconnect ${integration.name}? This will revoke access and you'll need to reconnect to use this integration again.`;

  const handleConnect = async () => {
    if (isConnected || isConnecting) return;

    // For bearer-auth integrations, show modal instead of direct connect
    if (integration.authType === "bearer" && integration.requiresAuth) {
      setShowBearerModal(true);
      return;
    }

    setIsConnecting(true);
    try {
      const result = await onConnect(integration.id);
      // On an OAuth redirect the browser is navigating away — keep the button in
      // its loading state instead of flashing back to idle for a split second.
      if (result?.status === "redirecting" || result?.status === "redirect") {
        return;
      }
      setIsConnecting(false);
    } catch {
      // Error toast is handled in the hook
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
    if (!isConnected || !onDisconnect) return;
    setShowDisconnectDialog(true);
  };

  const confirmDisconnect = async () => {
    if (!onDisconnect) return;
    setIsDisconnecting(true);
    try {
      await onDisconnect(integration.id);
    } finally {
      setIsDisconnecting(false);
      setShowDisconnectDialog(false);
    }
  };

  const handleDelete = () => {
    if (!onDelete) return;
    setShowDeleteDialog(true);
  };

  const confirmDelete = async () => {
    if (!onDelete) return;
    setIsDeleting(true);
    try {
      await onDelete(integration.id);
    } finally {
      setIsDeleting(false);
      setShowDeleteDialog(false);
    }
  };

  const handlePublish = () => {
    if (isPublishing) return;
    setShowPublishDialog(true);
  };

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(
        `${window.location.origin}/marketplace/${integration.slug}`,
      );
      toast.success("Link copied to clipboard!");
    } catch {
      toast.error("Failed to copy link to clipboard");
    }
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
          showDeleteButton ? (
            // Not-connected custom integration: Retry + Delete grouped together,
            // like the connected-state actions.
            <ButtonGroup variant="flat" className="w-full" fullWidth>
              <Button
                className="w-full"
                color={showRetry ? "warning" : "primary"}
                onPress={handleConnect}
                isLoading={isConnecting}
                isDisabled={isConnecting}
                startContent={
                  isConnecting ? undefined : showRetry ? (
                    <RedoIcon width={18} height={18} />
                  ) : (
                    <ConnectIcon width={18} height={18} />
                  )
                }
              >
                {showRetry ? "Retry Connection" : "Connect"}
              </Button>
              <Button
                className="w-full"
                color="danger"
                onPress={handleDelete}
                isLoading={isDeleting}
                isDisabled={isDeleting}
                startContent={
                  <RemoveCircleIcon
                    width={18}
                    height={18}
                    className="outline-0!"
                  />
                }
              >
                {deleteButtonText}
              </Button>
            </ButtonGroup>
          ) : (
            // Warning colour for a retry (a previous connect didn't complete),
            // primary blue for a first-time connect.
            <RaisedButton
              color={showRetry ? "#f5a524" : "#00bbff"}
              className="font-medium text-black!"
              onClick={handleConnect}
              disabled={isConnecting}
            >
              {isConnecting ? (
                <>
                  <Spinner size="sm" color="default" />
                  Connecting...
                </>
              ) : showRetry ? (
                <>
                  <RedoIcon width={18} height={18} />
                  Retry Connection
                </>
              ) : (
                <>
                  <ConnectIcon width={18} height={18} />
                  Connect
                </>
              )}
            </RaisedButton>
          )
        ) : (
          <ButtonGroup variant="flat" className="w-full" fullWidth>
            {onDisconnect && (
              <Tooltip content={`${disconnectLabel} this integration`}>
                <Button
                  isIconOnly={useIconOnly}
                  className="w-full"
                  color="danger"
                  onPress={handleDisconnect}
                  isLoading={isDisconnecting}
                  isDisabled={isDisconnecting}
                  aria-label={disconnectLabel}
                  startContent={
                    isDisconnecting ? undefined : isCustom ? (
                      <RemoveCircleIcon
                        width={18}
                        height={18}
                        className="outline-0!"
                      />
                    ) : (
                      <Unlink04Icon
                        width={18}
                        height={18}
                        className="outline-0!"
                      />
                    )
                  }
                >
                  {!useIconOnly && disconnectLabel}
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
                  onPress={handleShare}
                  aria-label="Share"
                  startContent={<Share08Icon width={18} height={18} />}
                >
                  {!useIconOnly && "Share"}
                </Button>
              </Tooltip>
            )}
          </ButtonGroup>
        )}
        {isConnected && (
          <div className="mt-3">
            <IntegrationInstructionsEditor
              integration={integration}
              toolNames={toolMentionNames}
            />
          </div>
        )}
        {integrationTools.length > 0 && (
          <h2 className="mt-3 text-sm font-medium text-zinc-300 relative right-1">
            Available tools ({integrationTools.length})
          </h2>
        )}
        {isSettling && isConnected && integrationTools.length === 0 && (
          <h2 className="mt-3 text-sm font-medium text-zinc-300 relative right-1">
            Setting up tools
          </h2>
        )}
      </SidebarHeader>

      <SidebarContent className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {integrationTools.length > 0 && (
          <div className="flex-1 min-h-0 overflow-y-auto pb-2">
            <div className="flex flex-wrap gap-2 content-start">
              {integrationTools.map((tool) => (
                <Chip
                  key={tool.name}
                  variant="bordered"
                  color="default"
                  radius="full"
                  className="font-light border-1 text-zinc-300"
                >
                  {tool.label}
                </Chip>
              ))}
            </div>
          </div>
        )}
        {isSettling && isConnected && integrationTools.length === 0 && (
          <div className="flex-1 min-h-0 overflow-y-auto pb-2">
            <div className="flex flex-wrap gap-2 content-start">
              {SETTLING_SKELETON_WIDTHS.map((width) => (
                <Skeleton key={width} className={`h-7 ${width} rounded-full`} />
              ))}
            </div>
          </div>
        )}

        <div className="shrink-0 pb-4">
          <IntegrationRelatedWorkflows integrationId={integration.id} />
        </div>
      </SidebarContent>

      <ConfirmationDialog
        isOpen={showDisconnectDialog}
        title={disconnectDialogTitle}
        message={disconnectDialogMessage}
        confirmText={disconnectLabel}
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
