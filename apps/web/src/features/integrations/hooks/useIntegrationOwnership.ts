import type { MyIntegrationItem } from "@shared/api/generated";
import { useMemo } from "react";

import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

/**
 * Ownership of a custom integration relative to the current user:
 * - own: a custom integration the current user created
 * - forked: a custom integration created by someone else (added from the marketplace)
 */
export function useIntegrationOwnership(integration: MyIntegrationItem) {
  const currentUserId = useCurrentUser()?.user_id;

  const isOwnIntegration = useMemo(
    () =>
      integration.source === "custom" &&
      !!integration.createdBy &&
      integration.createdBy === currentUserId,
    [integration.source, integration.createdBy, currentUserId],
  );

  const isForkedIntegration = useMemo(
    () =>
      integration.source === "custom" &&
      !!integration.createdBy &&
      integration.createdBy !== currentUserId,
    [integration.source, integration.createdBy, currentUserId],
  );

  return { isOwnIntegration, isForkedIntegration };
}
