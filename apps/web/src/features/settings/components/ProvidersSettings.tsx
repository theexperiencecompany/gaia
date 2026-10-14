"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { useMemo, useState } from "react";
import type { CredentialProvider } from "@/features/settings/api/providersApi";
import { ConfigureProviderModal } from "@/features/settings/components/providers/ConfigureProviderModal";
import { ProviderFavicon } from "@/features/settings/components/providers/ProviderFavicon";
import { resolveProviderRow } from "@/features/settings/components/providers/providerRows";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useProviderConfigs } from "@/features/settings/hooks/useProviderConfigs";
import {
  isProviderOffered,
  savedCredentialOverridesEnv,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";
import { customPresetsFromCatalog } from "@/features/setup-wizard/utils/providerCards";

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

export function ProvidersSettings() {
  const { data: status, refetch: refetchStatus } = useSetupStatus();
  const {
    data: storedConfigs,
    isLoading: isLoadingConfigs,
    refetch: refetchConfigs,
  } = useProviderConfigs();
  const { data: catalog, isError: isCatalogError } = useProviderCatalog();
  const [editingKey, setEditingKey] = useState<CredentialProvider | null>(null);

  // The catalog serves every credential-store provider in display order.
  const { displayRows, presets } = useMemo(
    () =>
      catalog
        ? {
            displayRows: (
              Object.keys(catalog.providers) as CredentialProvider[]
            )
              .filter((key) => isProviderOffered(status, key))
              .map((key) => resolveProviderRow(key, catalog)),
            presets: customPresetsFromCatalog(catalog),
          }
        : { displayRows: [], presets: [] },
    [catalog, status],
  );

  const editingRow = displayRows.find((r) => r.key === editingKey) ?? null;

  return (
    <SettingsPage>
      <SettingsSection description="Connect the AI providers, tools, and integrations GAIA runs on.">
        {!catalog && !isCatalogError && <Spinner size="sm" />}
        {isCatalogError && (
          <p className="text-sm text-zinc-400">
            Couldn&apos;t load the provider list. Reload the page to try again.
          </p>
        )}
        {displayRows.map((row) => {
          const configured = status?.providers?.[row.key]?.configured === true;

          return (
            <SettingsRow
              key={row.key}
              label={row.label}
              description={
                savedCredentialOverridesEnv(status, row.key)
                  ? `${row.description} Your saved key overrides a different one set in the environment.`
                  : row.description
              }
              icon={<ProviderFavicon domain={row.faviconDomain} />}
            >
              <div className="flex items-center gap-3">
                <StatusBadge configured={configured} />
                <Button
                  variant="flat"
                  color="default"
                  size="sm"
                  className="text-xs"
                  isDisabled={isLoadingConfigs}
                  onPress={() => setEditingKey(row.key)}
                >
                  Configure
                </Button>
              </div>
            </SettingsRow>
          );
        })}
      </SettingsSection>

      {editingRow && (
        <ConfigureProviderModal
          key={editingRow.key}
          row={editingRow}
          presets={presets}
          stored={storedConfigs?.[editingRow.key]}
          isConfigured={
            status?.providers?.[editingRow.key]?.configured === true
          }
          onSaved={() => {
            void refetchStatus();
            void refetchConfigs();
            setEditingKey(null);
          }}
          onClose={() => setEditingKey(null)}
        />
      )}
    </SettingsPage>
  );
}
