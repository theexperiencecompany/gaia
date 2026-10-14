"use client";

import { Spinner } from "@heroui/spinner";
import { useMemo, useState } from "react";
import type { CredentialProvider } from "@/features/settings/api/providersApi";
import { ConfigureProviderModal } from "@/features/settings/components/providers/ConfigureProviderModal";
import { ProviderFeatureSection } from "@/features/settings/components/providers/ProviderFeatureSection";
import {
  groupProvidersByFeature,
  resolveProviderRow,
} from "@/features/settings/components/providers/providerRows";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useProviderConfigs } from "@/features/settings/hooks/useProviderConfigs";
import {
  isProviderConfigured,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";
import { customPresetsFromCatalog } from "@/features/setup-wizard/utils/providerCards";

export function ProvidersSettings() {
  const { data: status, refetch: refetchStatus } = useSetupStatus();
  const {
    data: storedConfigs,
    isLoading: isLoadingConfigs,
    refetch: refetchConfigs,
  } = useProviderConfigs();
  const { data: catalog, isError: isCatalogError } = useProviderCatalog();
  const [editingKey, setEditingKey] = useState<CredentialProvider | null>(null);

  const presets = useMemo(
    () => (catalog ? customPresetsFromCatalog(catalog) : []),
    [catalog],
  );
  const groups = catalog ? groupProvidersByFeature(catalog, status) : [];
  const editingRow =
    catalog && editingKey ? resolveProviderRow(editingKey, catalog) : null;

  return (
    <SettingsPage>
      {!catalog && !isCatalogError && <Spinner size="sm" />}
      {isCatalogError && (
        <p className="text-sm text-zinc-400">
          Couldn&apos;t load the provider list. Reload the page to try again.
        </p>
      )}
      {catalog &&
        groups.map((group) => (
          <ProviderFeatureSection
            key={group.key}
            group={group}
            catalog={catalog}
            status={status}
            isDisabled={isLoadingConfigs}
            onConfigure={setEditingKey}
          />
        ))}

      {editingRow && (
        <ConfigureProviderModal
          key={editingRow.key}
          row={editingRow}
          presets={presets}
          stored={storedConfigs?.[editingRow.key]}
          isConfigured={isProviderConfigured(status, editingRow.key)}
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
