"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import {
  instructionsQueryOptions,
  useInstructions,
} from "@/features/instructions";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { IntegrationInstructionsModal } from "@/features/integrations/components/IntegrationInstructionsModal";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useIntegrationTools } from "@/features/integrations/hooks/useIntegrationTools";
import type { Integration } from "@/features/integrations/types";
import { instructionsPreview } from "@/features/integrations/utils/instructionsPreview";
import { GlobalInstructionsEditor } from "@/features/settings/components/GlobalInstructionsEditor";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";

interface InstructionsModalHostProps {
  integration: Integration;
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Mounted per selected integration so the instructions/tools hooks are keyed
 * to one integration at a time.
 */
const InstructionsModalHost = ({
  integration,
  isOpen,
  onClose,
}: InstructionsModalHostProps) => {
  const instructions = useInstructions(integration.id);
  const { mentionNames } = useIntegrationTools(integration, integration.name);

  return (
    <IntegrationInstructionsModal
      isOpen={isOpen}
      onClose={onClose}
      integration={integration}
      instructions={instructions}
      toolNames={mentionNames}
    />
  );
};

const SKELETON_ROW_COUNT = 3;
const SKELETON_KEYS = Array.from(
  { length: SKELETON_ROW_COUNT },
  (_, index) => `instructions-skeleton-${index}`,
);

export function IntegrationInstructionsSettings() {
  const router = useRouter();
  const { integrations, isLoading: integrationsLoading } = useIntegrations();

  const connected = useMemo(
    () =>
      integrations.filter((integration) => integration.status === "connected"),
    [integrations],
  );

  // Same query options as useInstructions, so opening a row's modal is a cache hit.
  const instructionQueries = useQueries({
    queries: connected.map((integration) =>
      instructionsQueryOptions(integration.id),
    ),
  });

  const [selected, setSelected] = useState<Integration | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const isLoading =
    integrationsLoading || instructionQueries.some((query) => query.isLoading);

  const openModal = (integration: Integration) => {
    setSelected(integration);
    setIsModalOpen(true);
  };

  return (
    <SettingsPage>
      <GlobalInstructionsEditor />

      <SettingsSection
        title="Apps"
        description="Tap a connected app to tell GAIA how to use it."
      >
        {isLoading ? (
          SKELETON_KEYS.map((key) => (
            <div key={key} className="flex items-center gap-3 px-4 py-3.5">
              <Skeleton className="size-8 rounded-lg" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-32 rounded-lg" />
                <Skeleton className="h-3 w-48 rounded-lg" />
              </div>
            </div>
          ))
        ) : connected.length === 0 ? (
          <SettingsRow
            label="No connected apps"
            description="Connect an app to start adding custom instructions."
          >
            <Button
              size="sm"
              variant="flat"
              className="rounded-xl"
              onPress={() => router.push("/integrations")}
            >
              Browse integrations
            </Button>
          </SettingsRow>
        ) : (
          connected.map((integration, index) => {
            const content = instructionQueries[index]?.data?.content ?? "";
            const preview = instructionsPreview(content);
            return (
              <SettingsRow
                key={integration.id}
                label={integration.name}
                description={preview || "No instructions yet"}
                icon={
                  <IntegrationIcon
                    integrationId={integration.id}
                    iconUrl={integration.iconUrl}
                    category={integration.category}
                    size={22}
                  />
                }
                onClick={() => openModal(integration)}
              >
                <ChevronRight className="h-4 w-4 text-zinc-500" />
              </SettingsRow>
            );
          })
        )}
      </SettingsSection>

      {selected && (
        <InstructionsModalHost
          key={selected.id}
          integration={selected}
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
        />
      )}
    </SettingsPage>
  );
}
