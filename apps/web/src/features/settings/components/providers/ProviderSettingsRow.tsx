"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import { ProviderFavicon } from "@/features/settings/components/providers/ProviderFavicon";
import type { CatalogProviderRow } from "@/features/settings/components/providers/providerRows";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";

function StatusBadge({ configured }: { configured: boolean }) {
  if (configured) {
    return (
      <span className="flex items-center gap-1 rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Connected
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs font-medium text-zinc-400">
      <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" />
      Not configured
    </span>
  );
}

interface ProviderSettingsRowProps {
  row: CatalogProviderRow;
  configured: boolean;
  /** The saved key overrides a different one set in the environment. */
  overridesEnv: boolean;
  isDisabled: boolean;
  onConfigure: () => void;
}

export function ProviderSettingsRow({
  row,
  configured,
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
      icon={<ProviderFavicon domain={row.faviconDomain} />}
    >
      <div className="flex items-center gap-3">
        <StatusBadge configured={configured} />
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
