"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import { useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi } from "@/features/integrations/api/integrationsApi";
import { IntegrationInstructionsModal } from "@/features/integrations/components/IntegrationInstructionsModal";
import { useIntegrationInstructions } from "@/features/integrations/hooks/useIntegrationInstructions";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useIntegrationTools } from "@/features/integrations/hooks/useIntegrationTools";
import type { Integration } from "@/features/integrations/types";
import { instructionsPreview } from "@/features/integrations/utils/instructionsPreview";
import { StatusIndicator } from "@/features/settings/components/StatusIndicator";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useGlobalCustomInstructions } from "@/features/settings/hooks/useGlobalCustomInstructions";

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
  const { instructions, isSaving, save } = useIntegrationInstructions(
    integration.id,
  );
  const { mentionNames } = useIntegrationTools(integration, integration.name);

  return (
    <IntegrationInstructionsModal
      isOpen={isOpen}
      onClose={onClose}
      integration={integration}
      savedContent={instructions?.content ?? ""}
      isSaving={isSaving}
      toolNames={mentionNames}
      onSave={save}
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
  const globalInstructions = useGlobalCustomInstructions();
  const { integrations, isLoading: integrationsLoading } = useIntegrations();

  const connected = useMemo(
    () =>
      integrations.filter((integration) => integration.status === "connected"),
    [integrations],
  );

  // Same query keys as useIntegrationInstructions, so opening the modal for a
  // row is an instant cache hit.
  const instructionQueries = useQueries({
    queries: connected.map((integration) => ({
      queryKey: ["integrations", "instructions", integration.id],
      queryFn: () => integrationsApi.getIntegrationInstructions(integration.id),
      staleTime: 0,
    })),
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
      <div>
        <p className="text-sm text-white">Custom Instructions</p>
        <p className="mt-0.5 mb-3 text-xs text-zinc-500">
          Included in every conversation.
        </p>
        <Textarea
          placeholder="Add any specific instructions for how GAIA should assist you..."
          value={globalInstructions.value}
          onChange={(e) => globalInstructions.onChange(e.target.value)}
          minRows={3}
          classNames={{
            input: "bg-zinc-800/50 text-sm",
            inputWrapper: "bg-zinc-800/50 hover:bg-zinc-700/50",
          }}
        />
      </div>

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
                icon={getToolCategoryIcon(
                  integration.id,
                  { size: 22, width: 22, height: 22, showBackground: false },
                  integration.iconUrl,
                )}
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
          integration={selected}
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
        />
      )}

      <StatusIndicator
        isUpdating={globalInstructions.isSaving}
        hasUnsavedChanges={globalInstructions.hasUnsavedChanges}
      />
    </SettingsPage>
  );
}
