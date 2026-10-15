"use client";

import { Spinner } from "@heroui/spinner";
import { useSearchParams } from "next/navigation";
import { ProviderFeatureSection } from "@/features/settings/components/providers/ProviderFeatureSection";
import {
  FEATURE_FOCUS_PARAM,
  groupProvidersByFeature,
} from "@/features/settings/components/providers/providerRows";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";

export function ProvidersSettings() {
  const { data: status, refetch: refetchStatus } = useSetupStatus();
  const { data: catalog, isError: isCatalogError } = useProviderCatalog();
  const groups = catalog ? groupProvidersByFeature(catalog, status) : [];
  const focusedFeature = useSearchParams().get(FEATURE_FOCUS_PARAM);

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
            isFocused={group.key === focusedFeature}
            onSaved={() => {
              void refetchStatus();
            }}
          />
        ))}
    </SettingsPage>
  );
}
