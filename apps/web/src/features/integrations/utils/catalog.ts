import type { MyIntegrationItem } from "@shared/api/generated";
import {
  INTEGRATION_STATE_ORDER,
  integrationConnectionState,
} from "@shared/utils";
import type { IntegrationStatus } from "../types";

/** Whether a connected integration is still discovering its tools, as the server reports it. */
export function isSettingUpTools(integration: MyIntegrationItem): boolean {
  return (
    integration.status === "connected" && integration.toolsSetup === "running"
  );
}

/** Needs-attention first (expired, then created), then connected, then the rest. */
export function byConnectionStateThenName(
  a: MyIntegrationItem,
  b: MyIntegrationItem,
): number {
  const priorityA =
    INTEGRATION_STATE_ORDER[integrationConnectionState(a.status)];
  const priorityB =
    INTEGRATION_STATE_ORDER[integrationConnectionState(b.status)];

  if (priorityA !== priorityB) return priorityA - priorityB;
  return a.name.localeCompare(b.name);
}

/**
 * The connection status of one integration, for surfaces outside the
 * integrations page.
 *
 * Carries the raw `status`, not just `connected`: without it a caller cannot
 * tell an integration that was never set up from one whose grant died, and
 * renders a first-time "Connect" for both.
 */
export function findIntegrationStatus(
  items: readonly MyIntegrationItem[],
  integrationId: string,
): IntegrationStatus | undefined {
  const item = items.find(
    (i) => i.id.toLowerCase() === integrationId.toLowerCase(),
  );
  if (!item) return undefined;

  return {
    integrationId: item.id,
    connected: item.status === "connected",
    status: item.status,
  };
}
