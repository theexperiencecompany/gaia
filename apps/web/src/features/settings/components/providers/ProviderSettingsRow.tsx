"use client";

import { Button } from "@heroui/button";
import Link from "next/link";
import { ProviderFavicon } from "@/features/settings/components/providers/ProviderFavicon";
import type { CatalogProviderRow } from "@/features/settings/components/providers/providerRows";
import { StatusBadge } from "@/features/settings/components/providers/StatusBadge";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";

interface ProviderSettingsRowProps {
  row: CatalogProviderRow;
  isConnected: boolean;
  /** The saved key overrides a different one set in the environment. */
  overridesEnv: boolean;
  isDisabled: boolean;
  onConfigure: () => void;
}

export function ProviderSettingsRow({
  row,
  isConnected,
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
        {isConnected && <StatusBadge label="Connected" active />}
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
            color={isConnected ? "default" : "primary"}
            size="sm"
            className="text-xs"
            isDisabled={isDisabled}
            onPress={onConfigure}
          >
            {configureLabel(row, isConnected)}
          </Button>
        )}
      </div>
    </SettingsRow>
  );
}

function configureLabel(row: CatalogProviderRow, isConnected: boolean) {
  if (isConnected) return "Configure";
  return row.showApiKey ? "Add key" : "Add address";
}
