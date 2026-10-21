import type {
  IntegrationConnectionData,
  IntegrationManagedBy,
  IntegrationStatusValue,
} from "../types";

/** Overlay a separately-fetched server status on the catalog's last-known status. */
export function reconcileIntegrationStatus(
  snapshotStatus: IntegrationStatusValue,
  connected: boolean | undefined,
  managedBy: IntegrationManagedBy | undefined,
  requiresAuth: boolean | undefined,
): IntegrationStatusValue {
  if (connected === undefined) return snapshotStatus;
  if (connected && snapshotStatus !== "connected") {
    return "connected";
  }
  if (
    !connected &&
    snapshotStatus === "connected" &&
    managedBy === "mcp" &&
    requiresAuth
  ) {
    return "created";
  }
  return snapshotStatus;
}

/**
 * How the integrations UI presents one integration's connection state.
 *
 * - `connected` — usable now.
 * - `pending` — added but never authenticated; the action is a retry.
 * - `expired` — was connected and the upstream grant died; the action is a
 *   reconnect, and saying "Connect" here would hide that something broke.
 * - `disconnected` — never connected; the action is a first-time connect.
 */
export type IntegrationConnectionState =
  | "connected"
  | "pending"
  | "expired"
  | "disconnected";

/**
 * Collapse the backend status into the states the UI renders. Any value this
 * build does not know — a status the API grew after it shipped — degrades to
 * `disconnected`, so a new state can never render blank or, worse, as usable.
 */
export function integrationConnectionState(
  status: IntegrationStatusValue | string | undefined,
): IntegrationConnectionState {
  switch (status) {
    case "connected":
      return "connected";
    case "created":
      return "pending";
    case "expired":
      return "expired";
    default:
      return "disconnected";
  }
}

/** What an `integration_connection_required` chat card asks the user to do. */
export type ConnectionPromptState = IntegrationConnectionState | "add_account";

/**
 * The state an `integration_connection_required` chat card renders.
 *
 * The payload's `expired` flag wins over the live integrations list: the
 * dead-account path expires the connection in the same turn it streams the
 * card, so the list is still reporting the pre-expiry status. An add-account
 * payload keeps its action on an integration the list reports as connected.
 * Messages streamed before either flag existed fall back to the list.
 */
export function connectionPromptState(
  prompt: Pick<IntegrationConnectionData, "expired" | "add_account">,
  status: IntegrationStatusValue | string | undefined,
): ConnectionPromptState {
  if (prompt.expired) return "expired";
  if (prompt.add_account) return "add_account";
  return integrationConnectionState(status);
}

/** Label for the button that resolves each state. */
export const CONNECT_ACTION_LABEL: Record<IntegrationConnectionState, string> =
  {
    connected: "Connected",
    pending: "Retry",
    expired: "Reconnect",
    disconnected: "Connect",
  };

/** Label for a connection prompt card's button. */
export const PROMPT_ACTION_LABEL: Record<ConnectionPromptState, string> = {
  ...CONNECT_ACTION_LABEL,
  add_account: "Add account",
};

/** Display order: things needing the user's attention first, then the catalog. */
export const INTEGRATION_STATE_ORDER: Record<
  IntegrationConnectionState,
  number
> = {
  expired: 0,
  pending: 1,
  connected: 2,
  disconnected: 3,
};
