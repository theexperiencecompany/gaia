/**
 * Connected-integration count for the wizard's Done summary. Loaded lazily
 * (and client-only) because it pulls the integrations catalog via react-query.
 * Renders a dash when the catalog is unavailable — the row is informational.
 */

"use client";

import { integrationConnectionState } from "@shared/utils";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

export default function ConnectedAppsCount() {
  const { integrations, isLoading } = useIntegrations();

  if (isLoading) return <span>Checking…</span>;

  const connected = integrations.filter(
    (i) => integrationConnectionState(i.status) === "connected",
  ).length;

  return <span>{connected > 0 ? `${connected} linked` : "None yet"}</span>;
}
