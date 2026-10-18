"use client";

import {
  ArrowRight02Icon,
  KeyIcon,
  PackageOpenIcon,
  PuzzleIcon,
  Search01Icon,
} from "@icons";
import { useState } from "react";
import {
  PromoBanner,
  type PromoBannerAction,
} from "@/components/shared/PromoBanner";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { COMPOSIO_SETUP_PATH } from "@/features/settings/api/composioSetupApi";
import { ComposioCatalogModal } from "@/features/settings/components/composio/ComposioCatalogModal";
import {
  isProviderConfigured,
  useDeployment,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";

interface IntegrationsBannerProps {
  onAddMcpServer: () => void;
}

/**
 * The integrations page's one banner. An instance admin is led to the Composio
 * catalog, or to adding its key first; everyone else to the Marketplace. The
 * remaining ways to add an app sit beside it as secondary actions.
 */
export function IntegrationsBanner({
  onAddMcpServer,
}: IntegrationsBannerProps) {
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);
  const { role } = useCurrentUser();
  const { data: status } = useSetupStatus();
  const canAddInstanceApps =
    useDeployment().instance_toolkits && role === "admin";
  const hasComposioKey = isProviderConfigured(status, "composio");

  const addMcpServer: PromoBannerAction = {
    label: "Add MCP server",
    icon: <PuzzleIcon className="h-4 w-4" />,
    onPress: onAddMcpServer,
  };
  const browseMarketplace: PromoBannerAction = {
    label: "Browse Marketplace",
    icon: <ArrowRight02Icon className="h-4 w-4" />,
    href: "/marketplace",
  };

  if (!canAddInstanceApps) {
    return (
      <PromoBanner
        icon={<PackageOpenIcon className="h-6 w-6 text-primary" />}
        title="Explore the Marketplace"
        description="Discover community integrations or publish your own for others to use."
        secondaryActions={[addMcpServer]}
        primaryAction={browseMarketplace}
      />
    );
  }

  const marketplace = { ...browseMarketplace, label: "Marketplace" };
  if (!hasComposioKey) {
    return (
      <PromoBanner
        icon={<KeyIcon className="h-6 w-6 text-primary" />}
        title="Unlock 1,600+ apps"
        description="Add a Composio key to enable Gmail, GitHub and the rest for everyone here."
        secondaryActions={[addMcpServer, marketplace]}
        primaryAction={{
          label: "Add Composio key",
          icon: <ArrowRight02Icon className="h-4 w-4" />,
          href: COMPOSIO_SETUP_PATH,
        }}
      />
    );
  }

  return (
    <>
      <PromoBanner
        icon={<Search01Icon className="h-6 w-6 text-primary" />}
        title="Add any app to this instance"
        description="Enable any of Composio's 1,600+ apps for everyone here, or add your own MCP server."
        secondaryActions={[addMcpServer, marketplace]}
        primaryAction={{
          label: "Browse 1,600+ apps",
          icon: <Search01Icon className="h-4 w-4" />,
          onPress: () => setIsCatalogOpen(true),
        }}
      />
      <ComposioCatalogModal
        isOpen={isCatalogOpen}
        onClose={() => setIsCatalogOpen(false)}
      />
    </>
  );
}
