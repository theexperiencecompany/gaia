"use client";

import { Link } from "@heroui/link";
import { Spinner } from "@heroui/spinner";
import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { ProviderFeatureList } from "@/features/settings/components/providers/ProviderFeatureList";
import {
  FEATURE_FOCUS_PARAM,
  featureAnchorId,
  groupProvidersByFeature,
} from "@/features/settings/components/providers/providerRows";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";

export function ProvidersSettings() {
  const { data: status } = useSetupStatus();
  const { data: catalog, isError: isCatalogError } = useProviderCatalog();
  const groups = catalog ? groupProvidersByFeature(catalog, status) : [];
  const focusParam = useSearchParams().get(FEATURE_FOCUS_PARAM);
  const focusedFeature =
    groups.find((group) => group.key === focusParam)?.key ?? null;

  useEffect(() => {
    if (!focusedFeature) return;
    document
      .getElementById(featureAnchorId(focusedFeature))
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusedFeature]);

  return (
    <SettingsPage>
      <p className="text-sm text-zinc-400">
        Keys that power GAIA&apos;s own tools, like search, email and running
        code. Apps you sign into, like Gmail or Calendar, live in{" "}
        <Link as={NextLink} href="/integrations" size="sm">
          Integrations
        </Link>
        .
      </p>
      {!catalog && !isCatalogError && <Spinner size="sm" />}
      {isCatalogError && (
        <p className="text-sm text-zinc-400">
          Couldn&apos;t load the provider list. Reload the page to try again.
        </p>
      )}
      {catalog && (
        <ProviderFeatureList
          // Remount once the linked feature resolves, so it opens expanded.
          key={focusedFeature ?? "all"}
          groups={groups}
          catalog={catalog}
          status={status}
          openFeature={focusedFeature}
        />
      )}
    </SettingsPage>
  );
}
