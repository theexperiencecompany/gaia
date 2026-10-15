"use client";

import { Button } from "@heroui/button";
import { Link as HeroLink } from "@heroui/link";
import { Select, SelectItem } from "@heroui/select";
import { Skeleton } from "@heroui/skeleton";
import { SquareArrowUpRight02Icon } from "@icons";
import Link from "next/link";
import { useMemo, useState } from "react";
import type {
  CredentialProvider,
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { useProviderConfigs } from "@/features/settings/hooks/useProviderConfigs";
import {
  isProviderConfigured,
  savedCredentialOverridesEnv,
} from "@/features/settings/hooks/useSetupStatus";
import { featureEngineLabel } from "@/features/settings/utils/providerCatalog";
import { customPresetsFromCatalog } from "@/features/setup-wizard/utils/providerCards";
import { ProviderCredentialForm } from "./ProviderCredentialForm";
import { ProviderFavicon } from "./ProviderFavicon";
import {
  type CatalogProviderRow,
  type FeatureGroup,
  initialPickedProvider,
} from "./providerRows";
import { StatusBadge } from "./StatusBadge";

const FAVICON_SIZE = 20;

interface FeatureProviderPickerProps {
  group: FeatureGroup;
  catalog: ProviderCatalog;
  status: SetupStatus | undefined;
  /** Fired after a save or removal so the caller refreshes setup status. */
  onSaved: () => void;
}

/**
 * One feature's providers: what it runs on now (the free built-in when no key
 * is set), one picker over its providers, and only the picked provider's fields.
 */
export function FeatureProviderPicker({
  group,
  catalog,
  status,
  onSaved,
}: FeatureProviderPickerProps) {
  const configs = useProviderConfigs();
  const presets = useMemo(() => customPresetsFromCatalog(catalog), [catalog]);
  // Only an explicit choice is stored: the default follows setup status, which may load after mount.
  const [pickedKey, setPickedKey] = useState<CredentialProvider | null>(null);
  const picked =
    group.rows.find((row) => row.key === pickedKey) ??
    initialPickedProvider(group);
  const servingKey = group.status?.in_use[0];

  const stateLabel = (row: CatalogProviderRow): string | null => {
    if (row.key === servingKey) return "In use";
    return isProviderConfigured(status, row.key) ? "Connected" : null;
  };

  const handleSaved = () => {
    void configs.refetch();
    onSaved();
  };

  if (group.status?.available === false) {
    return <UnavailableNotice group={group} />;
  }

  return (
    <div className="flex flex-col gap-3">
      <EngineLine group={group} catalog={catalog} />

      {group.rows.length > 1 ? (
        <Select
          label="Provider"
          size="sm"
          disallowEmptySelection
          selectedKeys={picked ? [picked.key] : []}
          description={picked?.description}
          onSelectionChange={(keys) => {
            const [first] = Array.from(keys);
            const row = group.rows.find((r) => r.key === first);
            if (row) setPickedKey(row.key);
          }}
          renderValue={(items) =>
            items.map((item) => {
              const row = group.rows.find((r) => r.key === item.key);
              if (!row) return null;
              return (
                <span key={row.key} className="flex items-center gap-2">
                  <ProviderFavicon
                    domain={row.favicon_domain}
                    size={FAVICON_SIZE}
                  />
                  {row.label}
                  {stateLabel(row) && (
                    <span className="text-xs text-zinc-500">
                      {stateLabel(row)}
                    </span>
                  )}
                </span>
              );
            })
          }
        >
          {group.rows.map((row) => (
            <SelectItem
              key={row.key}
              textValue={row.label}
              description={stateLabel(row) ?? undefined}
              startContent={
                <ProviderFavicon
                  domain={row.favicon_domain}
                  size={FAVICON_SIZE}
                />
              }
            >
              {row.label}
            </SelectItem>
          ))}
        </Select>
      ) : (
        picked && (
          <SingleProviderHeader row={picked} state={stateLabel(picked)} />
        )
      )}

      {picked?.managedAt ? (
        <Button
          as={Link}
          href={picked.managedAt.href}
          variant="flat"
          size="sm"
          className="self-start"
        >
          {picked.managedAt.label}
        </Button>
      ) : configs.isLoading ? (
        <Skeleton className="h-14 w-full rounded-xl" />
      ) : (
        picked && (
          <ProviderCredentialForm
            key={picked.key}
            row={picked}
            presets={presets}
            stored={configs.data?.[picked.key]}
            isConfigured={isProviderConfigured(status, picked.key)}
            overridesEnv={savedCredentialOverridesEnv(status, picked.key)}
            onSaved={handleSaved}
          />
        )
      )}
    </div>
  );
}

/** Why this instance cannot run the feature, and where the docs explain it. */
function UnavailableNotice({ group }: { group: FeatureGroup }) {
  const gap = group.spec.self_host_gap;
  if (!gap) {
    throw new Error(
      `Feature "${group.key}" is unavailable but the catalog gives no reason`,
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <p className="text-sm text-zinc-100">Not available on this instance</p>
      <p className="text-xs text-zinc-500">{gap.reason}</p>
      <HeroLink
        href={gap.docs_url}
        isExternal
        size="sm"
        className="inline-flex items-center gap-1 self-start text-xs"
      >
        Read the docs
        <SquareArrowUpRight02Icon size={12} />
      </HeroLink>
    </div>
  );
}

/** What the feature runs on now: the serving engine and its backups, or the free built-in. */
function EngineLine({
  group,
  catalog,
}: {
  group: FeatureGroup;
  catalog: ProviderCatalog;
}) {
  const { spec } = group;
  const [primary, ...backups] = (group.status?.in_use ?? []).map((engine) =>
    featureEngineLabel(engine, spec, catalog),
  );
  const builtIn = spec.built_in;

  const detail = (): string | undefined => {
    if (!primary) {
      return builtIn
        ? `${builtIn.label}: ${builtIn.description}`
        : "Pick a provider below to turn it on.";
    }
    if (backups.length > 0) return `Backup: ${backups.join(", ")}`;
    return primary === builtIn?.label ? builtIn.description : undefined;
  };

  return (
    <div>
      <p className="text-sm text-zinc-100">
        {primary ? `Using: ${primary}` : "Not running"}
      </p>
      {detail() && <p className="mt-0.5 text-xs text-zinc-500">{detail()}</p>}
    </div>
  );
}

function SingleProviderHeader({
  row,
  state,
}: {
  row: CatalogProviderRow;
  state: string | null;
}) {
  return (
    <div className="flex items-center gap-3">
      <ProviderFavicon domain={row.favicon_domain} size={FAVICON_SIZE} />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-zinc-100">{row.label}</p>
        <p className="text-xs text-zinc-500">{row.description}</p>
      </div>
      {state && <StatusBadge label={state} active />}
    </div>
  );
}
