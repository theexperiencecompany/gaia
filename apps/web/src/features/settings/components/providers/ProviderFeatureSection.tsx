"use client";

import type {
  CredentialProvider,
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { ProviderSettingsRow } from "@/features/settings/components/providers/ProviderSettingsRow";
import type { FeatureGroup } from "@/features/settings/components/providers/providerRows";
import { StatusBadge } from "@/features/settings/components/providers/StatusBadge";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import {
  isProviderConfigured,
  savedCredentialOverridesEnv,
} from "@/features/settings/hooks/useSetupStatus";
import { featureEngineLabel } from "@/features/settings/utils/providerCatalog";

interface ProviderFeatureSectionProps {
  group: FeatureGroup;
  catalog: ProviderCatalog;
  status: SetupStatus | undefined;
  isDisabled: boolean;
  onConfigure: (key: CredentialProvider) => void;
}

/** One feature's card: whether it works, what it runs on, and the providers that upgrade it. */
export function ProviderFeatureSection({
  group,
  catalog,
  status,
  isDisabled,
  onConfigure,
}: ProviderFeatureSectionProps) {
  const { spec, status: featureStatus, rows } = group;
  const working = featureStatus?.working === true;
  const [primary, ...backups] = (featureStatus?.in_use ?? []).map((engine) =>
    featureEngineLabel(engine, spec, catalog),
  );
  const builtIn = spec.built_in;

  const usingDescription = (): string | undefined => {
    if (!primary) {
      return builtIn
        ? `${builtIn.label}: ${builtIn.description}`
        : "Add a provider below to turn it on.";
    }
    if (backups.length > 0) return `Backup: ${backups.join(", ")}`;
    return primary === builtIn?.label ? builtIn.description : undefined;
  };

  return (
    <SettingsSection
      title={spec.label}
      titleAccessory={
        featureStatus && (
          <StatusBadge label={working ? "Working" : "Off"} active={working} />
        )
      }
      description={spec.description}
    >
      <SettingsRow
        label={primary ? `Using: ${primary}` : "Not running"}
        description={usingDescription()}
      />
      {rows.length > 0 && (
        <p className="px-4 pt-3 pb-1 text-xs font-medium text-zinc-500">
          {builtIn ? "Optional upgrades" : "Providers"}
        </p>
      )}
      {rows.map((row) => (
        <ProviderSettingsRow
          key={row.key}
          row={row}
          isConnected={isProviderConfigured(status, row.key)}
          overridesEnv={savedCredentialOverridesEnv(status, row.key)}
          isDisabled={isDisabled}
          onConfigure={() => onConfigure(row.key)}
        />
      ))}
    </SettingsSection>
  );
}
