import type { MyIntegrationItem } from "@shared/types";
import {
  INTEGRATION_STATE_ORDER,
  integrationConnectionState,
} from "@shared/utils";
import type { Integration, IntegrationStatus } from "../types";

/**
 * One entry of the personalized catalog in the shape the app consumes.
 *
 * `expiredAt` is normalized from `null` to `undefined` so a live connection
 * carries no timestamp at all, rather than a null the row would have to guard.
 */
export function toIntegration(item: MyIntegrationItem): Integration {
  return {
    id: item.id,
    name: item.name,
    description: item.description,
    category: item.category as Integration["category"],
    status: item.status,
    expiredAt: item.expiredAt ?? undefined,
    managedBy: item.managedBy,
    source: item.source,
    requiresAuth: item.requiresAuth,
    authType: item.authType ?? undefined,
    isFeatured: item.isFeatured,
    displayPriority: item.displayPriority,
    available: item.available,
    toolCount: item.toolCount,
    iconUrl: item.iconUrl ?? undefined,
    isPublic: item.isPublic ?? undefined,
    createdBy: item.createdBy ?? undefined,
    creator: item.creator ?? undefined,
    slug: item.slug ?? "",
  };
}

/** Needs-attention first (expired, then created), then connected, then the rest. */
export function byConnectionStateThenName(
  a: Integration,
  b: Integration,
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
