"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Spinner } from "@heroui/spinner";
import { Search01Icon, SquareArrowUpRight02Icon } from "@icons";
import { useState } from "react";
import { COMPOSIO_SETUP_DOCS_URL } from "@/features/settings/api/composioSetupApi";
import { extractProviderError } from "@/features/settings/api/providersApi";
import { ComposioAuthConfigRow } from "@/features/settings/components/ComposioAuthConfigRow";
import { ComposioCatalogModal } from "@/features/settings/components/composio/ComposioCatalogModal";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useComposioSetup } from "@/features/settings/hooks/useComposioSetup";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import {
  isProviderConfigured,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";
import { ProviderSetupCard } from "@/features/setup-wizard/components/ProviderSetupCard";
import { TOOL_PROVIDER_CARDS } from "@/features/setup-wizard/constants";
import { resolveProviderCard } from "@/features/setup-wizard/utils/providerCards";

const COMPOSIO_CARD = TOOL_PROVIDER_CARDS.find(
  (card) => card.key === "composio",
);

export function ComposioSetupSettings() {
  const { data: status, refetch: refetchStatus } = useSetupStatus();
  const { data: catalog } = useProviderCatalog();
  const composio = useComposioSetup();
  const [catalogSlug, setCatalogSlug] = useState<string | null>(null);
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);
  const canBrowse = composio.setup?.composio_configured === true;
  const openCatalog = (slug: string | null) => {
    setCatalogSlug(slug);
    setIsCatalogOpen(true);
  };
  const setUpCount =
    composio.setup?.integrations.filter((row) => row.auth_config_id !== null)
      .length ?? 0;

  return (
    <SettingsPage>
      <SettingsSection
        title="Composio key"
        description="Gmail, GitHub, Slack and the other app integrations connect through your own Composio project."
      >
        {catalog && COMPOSIO_CARD ? (
          <ProviderSetupCard
            config={resolveProviderCard(COMPOSIO_CARD, catalog)}
            isConfigured={isProviderConfigured(status, "composio")}
            onSaved={() => {
              void refetchStatus();
              void composio.refetch();
            }}
          />
        ) : (
          <Spinner size="sm" className="p-4" />
        )}
      </SettingsSection>

      <SettingsSection
        title="Integrations"
        titleAccessory={
          composio.setup && (
            <span className="text-xs text-zinc-500">
              {setUpCount} of {composio.setup.integrations.length} set up
            </span>
          )
        }
        description="Set up an integration in one click, or pick an auth config you already made in Composio. Browse the catalog to add any other app Composio supports."
      >
        <div className="flex justify-end p-2">
          <Button
            size="sm"
            variant="flat"
            color="primary"
            isDisabled={!canBrowse}
            startContent={<Search01Icon className="size-4" />}
            onPress={() => openCatalog(null)}
          >
            Browse Composio catalog
          </Button>
        </div>
        {composio.isLoading && <Spinner size="sm" className="p-4" />}
        {composio.error && (
          <p className="p-4 text-sm text-zinc-400">
            {extractProviderError(composio.error) ??
              "Couldn't load your Composio setup."}
          </p>
        )}
        {composio.setup && !composio.setup.composio_configured && (
          <p className="p-4 text-sm text-zinc-400">
            Add your Composio key above to find your auth configs automatically.
            You can also paste ids by hand.
          </p>
        )}
        {composio.setup?.integrations.map((row) => (
          <ComposioAuthConfigRow
            key={row.integration_id}
            row={row}
            value={composio.drafts[row.integration_id] ?? ""}
            onChange={(value) => composio.setDraft(row.integration_id, value)}
            onSetUp={canBrowse ? openCatalog : undefined}
          />
        ))}
      </SettingsSection>

      <div className="flex items-center justify-between">
        <Link
          href={COMPOSIO_SETUP_DOCS_URL}
          isExternal
          size="sm"
          className="text-zinc-400"
          anchorIcon={<SquareArrowUpRight02Icon className="ml-1 size-3.5" />}
          showAnchorIcon
        >
          How to set up Composio
        </Link>
        <Button
          color="primary"
          size="sm"
          isDisabled={!composio.isDirty}
          isLoading={composio.isSaving}
          onPress={composio.save}
        >
          Save
        </Button>
      </div>
      <ComposioCatalogModal
        key={catalogSlug ?? "catalog"}
        isOpen={isCatalogOpen}
        onClose={() => setIsCatalogOpen(false)}
        initialSlug={catalogSlug}
      />
    </SettingsPage>
  );
}
