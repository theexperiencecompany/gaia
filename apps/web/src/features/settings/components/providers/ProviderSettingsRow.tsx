"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import { ProviderFavicon } from "@/features/settings/components/providers/ProviderFavicon";
import type {
  CatalogProviderRow,
  ProviderRowState,
} from "@/features/settings/components/providers/providerRows";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { cn } from "@/lib/utils";

const STATE_BADGE: Record<
  ProviderRowState,
  { label: string; tone: string; dot: string }
> = {
  connected: {
    label: "Connected",
    tone: "bg-emerald-400/10 text-emerald-400",
    dot: "bg-emerald-400",
  },
  local_sandbox: {
    label: "Local sandbox active",
    tone: "bg-emerald-400/10 text-emerald-400",
    dot: "bg-emerald-400",
  },
  not_configured: {
    label: "Not configured",
    tone: "bg-zinc-700/50 text-zinc-400",
    dot: "bg-zinc-500",
  },
};

function StatusBadge({ state }: { state: ProviderRowState }) {
  const badge = STATE_BADGE[state];
  return (
    <span
      className={cn(
        "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        badge.tone,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", badge.dot)} />
      {badge.label}
    </span>
  );
}

interface ProviderSettingsRowProps {
  row: CatalogProviderRow;
  state: ProviderRowState;
  /** The saved key overrides a different one set in the environment. */
  overridesEnv: boolean;
  isDisabled: boolean;
  onConfigure: () => void;
}

export function ProviderSettingsRow({
  row,
  state,
  overridesEnv,
  isDisabled,
  onConfigure,
}: ProviderSettingsRowProps) {
  return (
    <SettingsRow
      label={row.label}
      description={
        overridesEnv
          ? `${row.description} Your saved key overrides a different one set in the environment.`
          : row.description
      }
      icon={<ProviderFavicon domain={row.favicon_domain} />}
    >
      <div className="flex items-center gap-3">
        <StatusBadge state={state} />
        {row.managedAt ? (
          <Button
            as={Link}
            href={row.managedAt.href}
            variant="flat"
            color="default"
            size="sm"
            className="text-xs"
          >
            {row.managedAt.label}
          </Button>
        ) : (
          <Button
            variant="flat"
            color="default"
            size="sm"
            className="text-xs"
            isDisabled={isDisabled}
            onPress={onConfigure}
          >
            Configure
          </Button>
        )}
      </div>
    </SettingsRow>
  );
}
