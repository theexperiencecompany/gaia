"use client";

import { Button, ButtonGroup } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { ConnectIcon, RedoIcon, RemoveCircleIcon } from "@icons";

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
      <Spinner size="sm" color="default" />
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
        className="font-medium text-black!"
        onClick={connect.onConnect}
        disabled={connect.isPending}
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
        onPress={connect.onConnect}
        isLoading={connect.isPending}
        isDisabled={connect.isPending}
        startContent={
          connect.isPending ? undefined : <RedoIcon width={18} height={18} />
        }
      >
        Retry
      </Button>
      {remove.kind === "delete" ? (
        <Button
          className="w-full"
          color="danger"
          onPress={remove.onDelete}
          isLoading={remove.isDeletePending}
          isDisabled={remove.isDeletePending}
          startContent={
            <RemoveCircleIcon width={18} height={18} className="outline-0!" />
          }
        >
          {remove.deleteText}
        </Button>
      ) : (
        <Button
          className="w-full"
          color="danger"
          onPress={remove.onDisconnect}
          isLoading={remove.isDisconnectPending}
          isDisabled={remove.isDisconnectPending}
          startContent={
            <RemoveCircleIcon width={18} height={18} className="outline-0!" />
          }
        >
          {remove.labelText}
        </Button>
      )}
    </ButtonGroup>
  );
}
