"use client";

import { Button, ButtonGroup } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { ConnectIcon, RedoIcon, RemoveCircleIcon } from "@icons";

import { RaisedButton } from "@/components/ui/raised-button";

interface NotConnectedActionsProps {
  showRetry: boolean;
  showDeleteButton: boolean;
  hasDisconnect: boolean;
  isConnecting: boolean;
  isDeleting: boolean;
  isDisconnecting: boolean;
  deleteButtonText: string;
  disconnectLabel: string;
  onConnect: () => void;
  onDelete: () => void;
  onDisconnect: () => void;
}

/**
 * Actions for a not-yet-connected (or "created") integration: Retry + a remove
 * action when available, otherwise a single Connect/Retry button.
 */
export function NotConnectedActions({
  showRetry,
  showDeleteButton,
  hasDisconnect,
  isConnecting,
  isDeleting,
  isDisconnecting,
  deleteButtonText,
  disconnectLabel,
  onConnect,
  onDelete,
  onDisconnect,
}: NotConnectedActionsProps) {
  let connectButtonContent: React.ReactNode;
  if (isConnecting) {
    connectButtonContent = (
      <>
        <Spinner size="sm" color="default" />
        Connecting...
      </>
    );
  } else if (showRetry) {
    connectButtonContent = (
      <>
        <RedoIcon width={18} height={18} />
        Retry
      </>
    );
  } else {
    connectButtonContent = (
      <>
        <ConnectIcon width={18} height={18} />
        Connect
      </>
    );
  }

  if (!showRetry || !(showDeleteButton || hasDisconnect)) {
    return (
      <RaisedButton
        color={showRetry ? "#f5a524" : "#00bbff"}
        className="font-medium text-black!"
        onClick={onConnect}
        disabled={isConnecting}
      >
        {connectButtonContent}
      </RaisedButton>
    );
  }

  return (
    <ButtonGroup variant="flat" className="w-full" fullWidth>
      <Button
        className="w-full"
        color="warning"
        onPress={onConnect}
        isLoading={isConnecting}
        isDisabled={isConnecting}
        startContent={
          isConnecting ? undefined : <RedoIcon width={18} height={18} />
        }
      >
        Retry
      </Button>
      {showDeleteButton ? (
        <Button
          className="w-full"
          color="danger"
          onPress={onDelete}
          isLoading={isDeleting}
          isDisabled={isDeleting}
          startContent={
            <RemoveCircleIcon width={18} height={18} className="outline-0!" />
          }
        >
          {deleteButtonText}
        </Button>
      ) : (
        <Button
          className="w-full"
          color="danger"
          onPress={onDisconnect}
          isLoading={isDisconnecting}
          isDisabled={isDisconnecting}
          startContent={
            <RemoveCircleIcon width={18} height={18} className="outline-0!" />
          }
        >
          {disconnectLabel}
        </Button>
      )}
    </ButtonGroup>
  );
}
