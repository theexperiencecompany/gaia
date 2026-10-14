"use client";

import { Spinner } from "@heroui/spinner";
import { useMemo, useState } from "react";
import type { CredentialProvider } from "@/features/settings/api/providersApi";
import { ConfigureProviderModal } from "@/features/settings/components/providers/ConfigureProviderModal";
import { ProviderSettingsRow } from "@/features/settings/components/providers/ProviderSettingsRow";
import {
  groupProviderRows,
  resolveProviderRow,
} from "@/features/settings/components/providers/providerRows";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useProviderConfigs } from "@/features/settings/hooks/useProviderConfigs";
import {
  isProviderConfigured,
  isProviderOffered,
  savedCredentialOverridesEnv,
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

  const sections = groupProviderRows(displayRows, (key) =>
    isProviderConfigured(status, key),
  );

  return (
    <SettingsPage>
      {!catalog && !isCatalogError && <Spinner size="sm" />}
      {isCatalogError && (
        <p className="text-sm text-zinc-400">
          Couldn&apos;t load the provider list. Reload the page to try again.
        </p>
      )}
      {sections.map((section) => (
        <SettingsSection
          key={section.key}
          title={section.title}
          description={section.description}
        >
          {section.rows.map((row) => (
            <ProviderSettingsRow
              key={row.key}
              row={row}
              configured={isProviderConfigured(status, row.key)}
              overridesEnv={savedCredentialOverridesEnv(status, row.key)}
              isDisabled={isLoadingConfigs}
              onConfigure={() => setEditingKey(row.key)}
            />
          ))}
        </SettingsSection>
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
