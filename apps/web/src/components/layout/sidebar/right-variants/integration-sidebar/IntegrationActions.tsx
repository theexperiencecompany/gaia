"use client";

import { RemoveCircleIcon, Unlink04Icon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import {
  integrationKeys,
  toolKeys,
} from "@/features/integrations/api/queryKeys";
import { BearerTokenModal } from "@/features/integrations/components/BearerTokenModal";
import { useBearerTokenModal } from "@/features/integrations/hooks/useBearerTokenModal";
import { useIntegrationOwnership } from "@/features/integrations/hooks/useIntegrationOwnership";
import type { Integration } from "@/features/integrations/types";
import { toast } from "@/lib/toast";

import { ConnectedActions } from "./ConnectedActions";
import { NotConnectedActions } from "./NotConnectedActions";

// Confirmation copy for the disconnect/remove action. Custom integrations are
// deleted (own) or removed from the workspace (forked); native integrations are
// disconnected (revoke access) or removed when not yet connected.
function getDisconnectDialogMessage(
  name: string,
  isCustom: boolean,
  isOwnIntegration: boolean,
  isConnected: boolean,
): string {
  if (isCustom) {
    return isOwnIntegration
      ? `Remove ${name}? This permanently deletes the integration and its tools, and can't be undone.`
      : `Remove ${name} from your workspace? You can add it again from the marketplace later.`;
  }
  return isConnected
    ? `Are you sure you want to disconnect ${name}? This will revoke access and you'll need to reconnect to use this integration again.`
    : `Remove ${name} from your workspace? You can add it again anytime.`;
}

interface IntegrationActionsProps {
  integration: Integration;
  isConnected: boolean;
  onConnect: (
    integrationId: string,
  ) => Promise<{ status: string; toolsCount?: number }>;
  onDisconnect?: (integrationId: string) => void;
  onDelete?: (integrationId: string) => Promise<void>;
  onPublish?: (integrationId: string) => Promise<void>;
  onUnpublish?: (integrationId: string) => Promise<void>;
}

/**
 * The connect / disconnect / publish / delete actions for an integration,
 * including the confirmation dialogs and the bearer-token modal. Owns all the
 * action state so the sidebar shell stays presentational; the button layouts
 * live in NotConnectedActions / ConnectedActions.
 */
export function IntegrationActions({
  integration,
  isConnected,
  onConnect,
  onDisconnect,
  onDelete,
  onPublish,
  onUnpublish,
}: IntegrationActionsProps) {
  const queryClient = useQueryClient();
  const { isOwnIntegration, isForkedIntegration } =
    useIntegrationOwnership(integration);

  const showRetry = integration.status === "created";
  const isCustom = integration.source === "custom";

  const [showDisconnectDialog, setShowDisconnectDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);

  const bearer = useBearerTokenModal({
    connect: (id, token) => integrationsApi.connectIntegration(id, token),
    onConnected: () => {
      toast.success(`Connected to ${integration.name}`);
      // Refresh data in the background so the sidebar reflects the new tools.
      queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
    },
  });

  // Show delete/remove button for non-connected custom integrations.
  const showDeleteButton = !isConnected && isCustom && !!onDelete;

  // Count visible buttons to decide whether to collapse to icon-only.
  const buttonCount = [
    !!onDisconnect,
    integration.isPublic, // View on Marketplace
    isOwnIntegration && integration.isPublic, // Unpublish
    isOwnIntegration && !integration.isPublic, // Publish
    integration.isPublic, // Share
  ].filter(Boolean).length;
  const useIconOnly = buttonCount >= 3;

  // A not-yet-connected (created) integration is "removed", not "disconnected".
  const disconnectLabel = isCustom || !isConnected ? "Remove" : "Disconnect";
  const disconnectDialogTitle =
    isCustom || !isConnected ? "Remove Integration" : "Disconnect Integration";
  const disconnectDialogMessage = getDisconnectDialogMessage(
    integration.name,
    isCustom,
    isOwnIntegration,
    isConnected,
  );

  const deleteButtonText = isForkedIntegration ? "Remove" : "Delete";
  const deleteDialogTitle = isForkedIntegration
    ? "Remove Integration"
    : "Delete Integration";
  const deleteDialogMessage = isForkedIntegration
    ? `Are you sure you want to remove ${integration.name} from your GAIA? You can add it again from the marketplace.`
    : `Are you sure you want to delete ${integration.name}? This action cannot be undone.`;
  const deleteDialogConfirmText = isForkedIntegration ? "Remove" : "Delete";

  const disconnectIcon = isCustom ? (
    <RemoveCircleIcon width={18} height={18} className="outline-0!" />
  ) : (
    <Unlink04Icon width={18} height={18} className="outline-0!" />
  );

  const handleConnect = async () => {
    if (isConnected || isConnecting) return;

    // For bearer-auth integrations, show modal instead of direct connect.
    if (integration.authType === "bearer" && integration.requiresAuth) {
      bearer.open(integration.id, integration.name);
      return;
    }

    setIsConnecting(true);
    try {
      const result = await onConnect(integration.id);
      // On an OAuth redirect the browser is navigating away — keep the button in
      // its loading state instead of flashing back to idle for a split second.
      if (result?.status === "redirecting") return;
      setIsConnecting(false);
    } catch {
      // Error toast is handled in the hook
      setIsConnecting(false);
    }
  };

  const handleDisconnect = () => {
    if (!onDisconnect) return;
    setShowDisconnectDialog(true);
  };

  const confirmDisconnect = async () => {
    if (!onDisconnect) return;
    // Dismiss the dialog immediately — the action runs in the background and
    // surfaces any failure via toast.
    setShowDisconnectDialog(false);
    setIsDisconnecting(true);
    try {
      await onDisconnect(integration.id);
    } finally {
      setIsDisconnecting(false);
    }
  };

  const handleDelete = () => {
    if (!onDelete) return;
    setShowDeleteDialog(true);
  };

  const confirmDelete = async () => {
    if (!onDelete) return;
    setShowDeleteDialog(false);
    setIsDeleting(true);
    try {
      await onDelete(integration.id);
    } finally {
      setIsDeleting(false);
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
    // Dismiss the dialog immediately — progress is conveyed by the loading
    // toast, and publishing navigates away on success.
    setShowPublishDialog(false);
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
    }
  };

  return (
    <>
      {!isConnected ? (
        <NotConnectedActions
          showRetry={showRetry}
          showDeleteButton={showDeleteButton}
          hasDisconnect={!!onDisconnect}
          isConnecting={isConnecting}
          isDeleting={isDeleting}
          isDisconnecting={isDisconnecting}
          deleteButtonText={deleteButtonText}
          disconnectLabel={disconnectLabel}
          onConnect={handleConnect}
          onDelete={handleDelete}
          onDisconnect={handleDisconnect}
        />
      ) : (
        <ConnectedActions
          integration={integration}
          useIconOnly={useIconOnly}
          isOwnIntegration={isOwnIntegration}
          hasDisconnect={!!onDisconnect}
          disconnectLabel={disconnectLabel}
          disconnectIcon={disconnectIcon}
          isDisconnecting={isDisconnecting}
          isPublishing={isPublishing}
          onDisconnect={handleDisconnect}
          onPublish={handlePublish}
          onShare={handleShare}
        />
      )}

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
        isOpen={bearer.isOpen}
        onClose={bearer.close}
        integrationId={bearer.integrationId}
        integrationName={bearer.integrationName}
        onSubmit={bearer.submit}
      />
    </>
  );
}
