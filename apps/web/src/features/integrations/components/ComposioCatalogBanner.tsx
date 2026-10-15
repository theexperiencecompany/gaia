"use client";

import { Search01Icon } from "@icons";
import { useState } from "react";
import { PromoBanner } from "@/components/shared/PromoBanner";
import { ComposioCatalogModal } from "@/features/settings/components/composio/ComposioCatalogModal";

/** The instance admin's way to add any Composio app from the integrations page. */
export function ComposioCatalogBanner() {
  const [isCatalogOpen, setIsCatalogOpen] = useState(false);

  return (
    <>
      <PromoBanner
        icon={<Search01Icon className="h-6 w-6 text-primary" />}
        title="Add any app to this instance"
        description="Enable any of Composio's 1,600+ apps for everyone here. MCP servers on your own network work too."
        primaryAction={{
          label: "Browse Composio catalog",
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
