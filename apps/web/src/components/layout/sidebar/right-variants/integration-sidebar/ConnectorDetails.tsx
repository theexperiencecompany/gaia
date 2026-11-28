"use client";

import { Skeleton } from "@heroui/react";
import { CheckmarkCircle02Icon } from "@icons";
import type { ConnectorCardInfo } from "@shared/api/generated";

import { ConnectorKeyInfo } from "@/features/integrations/components/ConnectorKeyInfo";
import { usePrimaryAccountName } from "@/features/integrations/hooks/usePrimaryAccountName";

interface ConnectorDetailsProps {
  integrationId: string;
  connector: ConnectorCardInfo;
  isConnected: boolean;
}

function ConnectedAs({ integrationId }: { integrationId: string }) {
  const { name, isLoading } = usePrimaryAccountName(integrationId);
  if (isLoading) return <Skeleton className="mt-3 h-10 w-full rounded-2xl" />;
  if (!name) return null;
  return (
    <p className="mt-3 flex items-center gap-2 rounded-2xl bg-zinc-800 p-3 text-sm text-zinc-300">
      <CheckmarkCircle02Icon className="size-4 shrink-0 text-success" />
      Connected as {name}
    </p>
  );
}

/** A connector's key details: where the key goes before connecting, whose account after. */
export function ConnectorDetails({
  integrationId,
  connector,
  isConnected,
}: ConnectorDetailsProps) {
  if (isConnected) return <ConnectedAs integrationId={integrationId} />;
  return (
    <div className="mt-3 rounded-2xl bg-zinc-800 p-3">
      <ConnectorKeyInfo connector={connector} />
    </div>
  );
}
