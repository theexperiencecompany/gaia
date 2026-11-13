"use client";

import { ButtonGroup, Spinner } from "@heroui/react";
import { ConnectIcon, RedoIcon, RemoveCircleIcon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";

import { RaisedButton } from "@/components/ui/raised-button";

/** The primary connect/retry action. */
interface ConnectAction {
  /** Status "created" integrations retry instead of connecting fresh. */
  showRetry: boolean;
  isPending: boolean;
  onConnect: () => void;
}

/**
 * The remove action; presence decides whether the actions collapse into a
 * single connect/retry button or a button group with a remove action.
 */
interface RemoveAction {
  /** "delete" removes a custom integration; "disconnect" revokes access. */
  kind: "delete" | "disconnect";
  deleteText: string;
  labelText: string;
  isDeletePending: boolean;
  isDisconnectPending: boolean;
  onDelete: () => void;
  onDisconnect: () => void;
}

interface NotConnectedActionsProps {
  connect: ConnectAction;
  remove?: RemoveAction | null;
}

/**
 * Actions for a not-yet-connected (or "created") integration: Retry + a remove
 * action when available, otherwise a single Connect/Retry button.
 */
export function NotConnectedActions({
  connect,
  remove = null,
}: NotConnectedActionsProps) {
  const connectButtonContent = connect.isPending ? (
    <>
      <Spinner size="sm" color="current" />
      Connecting...
    </>
  ) : connect.showRetry ? (
    <>
      <RedoIcon width={18} height={18} />
      Retry
    </>
  ) : (
    <>
      <ConnectIcon width={18} height={18} />
      Connect
    </>
  );

  if (!connect.showRetry || !remove) {
    return (
      <RaisedButton
        color={connect.showRetry ? "#f5a524" : "#00bbff"}
        className="font-medium"
        onClick={connect.onConnect}
        disabled={connect.isPending}
      >
        {connectButtonContent}
      </RaisedButton>
    );
  }

  return (
    <ButtonGroup variant="tertiary" className="w-full" fullWidth>
      <GaiaButton
        className="w-full"
        onPress={connect.onConnect}
        isPending={connect.isPending}
        isDisabled={connect.isPending}
        variant="primary"
      >
        {!connect.isPending && <RedoIcon width={18} height={18} />}
        Retry
      </GaiaButton>
      {remove.kind === "delete" ? (
        <GaiaButton
          className="w-full"
          onPress={remove.onDelete}
          isPending={remove.isDeletePending}
          isDisabled={remove.isDeletePending}
          variant="danger"
        >
          <RemoveCircleIcon width={18} height={18} className="outline-0!" />
          {remove.deleteText}
        </GaiaButton>
      ) : (
        <GaiaButton
          className="w-full"
          onPress={remove.onDisconnect}
          isPending={remove.isDisconnectPending}
          isDisabled={remove.isDisconnectPending}
          variant="danger"
        >
          <RemoveCircleIcon width={18} height={18} className="outline-0!" />
          {remove.labelText}
        </GaiaButton>
      )}
    </ButtonGroup>
  );
}
