"use client";

import { Spinner } from "@heroui/spinner";
import { PackageOpenIcon } from "@icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import ShareButton from "@/features/use-cases/components/ShareButton";

/** Title row with the integration icon, description and the share/add actions. */
export function IntegrationDetailHeader({
  integration,
  alreadyHasIntegration,
  isAdding,
  isAdded,
  onAdd,
  onView,
}: {
  readonly integration: PublicIntegrationResponse;
  readonly alreadyHasIntegration: boolean;
  readonly isAdding: boolean;
  readonly isAdded: boolean;
  readonly onAdd: () => void;
  readonly onView: () => void;
}) {
  return (
    <div className="flex w-full items-start justify-between gap-2">
      <div className="flex-1 space-y-2">
        <div className="flex items-center gap-4">
          <div className="flex max-w-12 min-w-12 min-h-12 max-h-12 items-center justify-center rounded-lg overflow-hidden">
            {getToolCategoryIcon(
              integration.integrationId,
              { size: 48, width: 48, height: 48, showBackground: false },
              integration.iconUrl || undefined,
            ) || (
              <div className="flex h-16 w-16 aspect-square items-center justify-center rounded-xl bg-zinc-700 font-medium text-zinc-300">
                <PackageOpenIcon width={48} height={48} />
              </div>
            )}
          </div>
          <h1 className="text-5xl font-medium text-foreground">
            {integration.name}
          </h1>
        </div>
        <p className="text-lg leading-relaxed text-zinc-500 max-w-5xl mt-6">
          {integration.description ||
            `Connect ${integration.name} to your AI assistant and automate your ${integration.category} workflows.`}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <ShareButton id={integration.integrationId} basePath="/marketplace" />
        {alreadyHasIntegration ? (
          <RaisedButton
            color="#00bbff"
            className="shrink-0 text-black!"
            onClick={onView}
          >
            View Integration
          </RaisedButton>
        ) : (
          <RaisedButton
            color="#00bbff"
            className="shrink-0 text-black!"
            onClick={onAdd}
            disabled={isAdding || isAdded}
          >
            {isAdding ? (
              <>
                <Spinner size="sm" color="default" />
                Adding...
              </>
            ) : isAdded ? (
              "Added to your GAIA"
            ) : (
              "Add to your GAIA"
            )}
          </RaisedButton>
        )}
      </div>
    </div>
  );
}
