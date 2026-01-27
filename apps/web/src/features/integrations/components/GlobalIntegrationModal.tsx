"use client";

import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";

import { useIntegrationModalStore } from "@/stores/integrationModalStore";

import { MCPIntegrationModal } from "./MCPIntegrationModal";

/**
 * Global wrapper for MCPIntegrationModal that connects to the store.
 * Render this once at the app layout level.
 *
 * After creating an integration, navigates to /integrations?id=X&refresh=true
 * which triggers the integrations page to open the sidebar.
 */
export function GlobalIntegrationModal() {
  const router = useRouter();
  const pathname = usePathname();
  const isOpen = useIntegrationModalStore((state) => state.isOpen);
  const closeModal = useIntegrationModalStore((state) => state.closeModal);

  // Handle when integration is created - navigate to integrations page with ID
  const handleIntegrationCreated = useCallback(
    (integrationId: string) => {
      // If already on integrations page, just add the query param
      // Otherwise navigate to integrations page
      if (pathname === "/integrations") {
        // Replace current URL with refresh param to trigger the page's useEffect
        router.replace(`/integrations?id=${integrationId}&refresh=true`, {
          scroll: false,
        });
      } else {
        // Navigate to integrations page
        router.push(`/integrations?id=${integrationId}&refresh=true`);
      }
    },
    [router, pathname],
  );

  return (
    <MCPIntegrationModal
      isOpen={isOpen}
      onClose={closeModal}
      onIntegrationCreated={handleIntegrationCreated}
    />
  );
}
