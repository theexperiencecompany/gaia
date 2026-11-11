import { Spinner } from "@heroui/spinner";
import { PackageOpenIcon } from "@icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import ShareButton from "@/features/use-cases/components/ShareButton";

interface AddButtonProps {
  isAdding: boolean;
  isAdded: boolean;
  alreadyHasIntegration: boolean;
  onAdd: () => void;
  onView: () => void;
}

interface IntegrationHeaderProps extends AddButtonProps {
  integration: PublicIntegrationResponse;
}

function AddButtonLabel({
  isAdding,
  isAdded,
}: Pick<AddButtonProps, "isAdding" | "isAdded">) {
  if (isAdding) {
    return (
      <>
        <Spinner size="sm" color="default" />
        Adding...
      </>
    );
  }
  return isAdded ? "Added to your GAIA" : "Add to your GAIA";
}

function AddButton({
  isAdding,
  isAdded,
  alreadyHasIntegration,
  onAdd,
  onView,
}: AddButtonProps) {
  if (alreadyHasIntegration) {
    return (
      <RaisedButton color="#00bbff" className="shrink-0" onClick={onView}>
        View Integration
      </RaisedButton>
    );
  }
  return (
    <RaisedButton
      color="#00bbff"
      className="shrink-0"
      onClick={onAdd}
      disabled={isAdding || isAdded}
    >
      <AddButtonLabel isAdding={isAdding} isAdded={isAdded} />
    </RaisedButton>
  );
}

export function IntegrationHeader({
  integration,
  ...addButtonProps
}: IntegrationHeaderProps) {
  return (
    <div className="flex w-full flex-col items-start justify-between gap-4 sm:flex-row sm:gap-2">
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
        <AddButton {...addButtonProps} />
      </div>
    </div>
  );
}
