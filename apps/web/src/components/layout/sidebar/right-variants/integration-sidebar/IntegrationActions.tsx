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

/** Title / message / confirm-label copy for a confirmation dialog. */
interface DialogCopy {
  title: string;
  message: string;
  confirmText: string;
}

// Confirmation copy for the disconnect/remove action. Custom integrations are
// removed (permanently deleted when own); native integrations are disconnected
// (revoke access) or removed when not yet connected. The confirm text doubles
// as the action button label shown before the dialog opens.
function getDisconnectDialogCopy(
  name: string,
  isCustom: boolean,
  isOwnIntegration: boolean,
  isConnected: boolean,
): DialogCopy {
  if (isCustom) {
    const message = isOwnIntegration
      ? `Remove ${name}? This permanently deletes the integration and its tools, and can't be undone.`
      : `Remove ${name} from your workspace? You can add it again from the marketplace later.`;
    return { title: "Remove Integration", message, confirmText: "Remove" };
  }
  if (!isConnected) {
    return {
      title: "Remove Integration",
      message: `Remove ${name} from your workspace? You can add it again anytime.`,
      confirmText: "Remove",
    };
  }
  return {
    title: "Disconnect Integration",
    message: `Are you sure you want to disconnect ${name}? This will revoke access and you'll need to reconnect to use this integration again.`,
    confirmText: "Disconnect",
  };
}

// Delete/remove copy for a not-yet-connected custom integration: own ones are
// deleted outright, forked ones are removed back to the marketplace. The
// confirm text doubles as the action button label.
function getDeleteDialogCopy(
  name: string,
  isForkedIntegration: boolean,
): DialogCopy {
  return isForkedIntegration
    ? {
        title: "Remove Integration",
        message: `Are you sure you want to remove ${name} from your GAIA? You can add it again from the marketplace.`,
        confirmText: "Remove",
      }
    : {
        title: "Delete Integration",
        message: `Are you sure you want to delete ${name}? This action cannot be undone.`,
        confirmText: "Delete",
      };
}

interface PublishDialogCopy extends DialogCopy {
  variant: "destructive" | "default";
}

// Publish/unpublish confirmation copy; unpublishing a public integration is
// destructive, publishing a private one is not.
function getPublishDialogCopy(
  name: string,
  isPublic?: boolean,
): PublishDialogCopy {
  return isPublic
    ? {
        title: "Unpublish Integration",
        message: `Are you sure you want to unpublish ${name}? It will no longer be visible in the community marketplace.`,
        confirmText: "Unpublish",
        variant: "destructive",
      }
    : {
        title: "Publish Integration",
        message: `Are you sure you want to publish ${name} to the community marketplace? Your integration name, description, and tool list will be publicly visible.`,
        confirmText: "Publish",
        variant: "default",
      };
}

type PublishHandler = (integrationId: string) => Promise<void>;
/** A publish/unpublish call already bound to a specific integration id. */
type BoundPublishAction = () => Promise<void>;

// Publishing toggles visibility: public integrations unpublish, private ones
// publish. Returns null when the matching handler isn't wired up.
function getPublishToggleAction(
  integrationId: string,
  isPublic?: boolean,
  onPublish?: PublishHandler,
  onUnpublish?: PublishHandler,
): BoundPublishAction | null {
  if (isPublic) {
    return onUnpublish ? () => onUnpublish(integrationId) : null;
  }
  return onPublish ? () => onPublish(integrationId) : null;
}

// Runs the resolved toggle; a missing handler surfaces as an error toast.
async function runPublishToggle(
  toggle: BoundPublishAction | null,
): Promise<void> {
  if (!toggle) {
    toast.error("Unable to publish: handler not available");
    return;
  }
  await toggle();
}

// Bearer-auth integrations collect their token through a modal instead of
// connecting directly.
function usesBearerAuth(integration: Integration): boolean {
  return integration.authType === "bearer" && Boolean(integration.requiresAuth);
}

function getDisconnectIcon(isCustom: boolean) {
  return isCustom ? (
    <RemoveCircleIcon width={18} height={18} className="outline-0!" />
  ) : (
    <Unlink04Icon width={18} height={18} className="outline-0!" />
  );
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
  const disconnectCopy = getDisconnectDialogCopy(
    integration.name,
    isCustom,
    isOwnIntegration,
    isConnected,
  );
  const deleteCopy = getDeleteDialogCopy(integration.name, isForkedIntegration);
  const publishCopy = getPublishDialogCopy(
    integration.name,
    integration.isPublic,
  );

  const disconnectIcon = getDisconnectIcon(isCustom);

  const handleConnect = async () => {
    if (isConnected || isConnecting) return;

    // For bearer-auth integrations, show modal instead of direct connect.
    if (usesBearerAuth(integration)) {
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
    const toggleAction = getPublishToggleAction(
      integration.id,
      integration.isPublic,
      onPublish,
      onUnpublish,
    );
    try {
      await runPublishToggle(toggleAction);
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
          connect={{
            showRetry,
            isPending: isConnecting,
            onConnect: handleConnect,
          }}
          remove={
            showDeleteButton || onDisconnect
              ? {
                  kind: showDeleteButton ? "delete" : "disconnect",
                  deleteText: deleteCopy.confirmText,
                  labelText: disconnectCopy.confirmText,
                  isDeletePending: isDeleting,
                  isDisconnectPending: isDisconnecting,
                  onDelete: handleDelete,
                  onDisconnect: handleDisconnect,
                }
              : null
          }
        />
      ) : (
        <ConnectedActions
          integration={integration}
          useIconOnly={useIconOnly}
          disconnect={
            onDisconnect
              ? {
                  label: disconnectCopy.confirmText,
                  icon: disconnectIcon,
                  isPending: isDisconnecting,
                  onDisconnect: handleDisconnect,
                }
              : null
          }
          publish={{ isPending: isPublishing, onPublish: handlePublish }}
          onShare={handleShare}
        />
      )}

      <ConfirmationDialog
        isOpen={showDisconnectDialog}
        title={disconnectCopy.title}
        message={disconnectCopy.message}
        confirmText={disconnectCopy.confirmText}
        cancelText="Cancel"
        variant="destructive"
        isLoading={isDisconnecting}
        onConfirm={confirmDisconnect}
        onCancel={() => setShowDisconnectDialog(false)}
      />

      <ConfirmationDialog
        isOpen={showDeleteDialog}
        title={deleteCopy.title}
        message={deleteCopy.message}
        confirmText={deleteCopy.confirmText}
        cancelText="Cancel"
        variant="destructive"
        isLoading={isDeleting}
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteDialog(false)}
      />

      <ConfirmationDialog
        isOpen={showPublishDialog}
        title={publishCopy.title}
        message={publishCopy.message}
        confirmText={publishCopy.confirmText}
        cancelText="Cancel"
        variant={publishCopy.variant}
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
