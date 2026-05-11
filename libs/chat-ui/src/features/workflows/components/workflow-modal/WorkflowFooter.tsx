import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import { GlobeIcon, LinkSquare02Icon, PlayIcon } from "@theexperiencecompany/gaia-icons/solid-rounded";

interface WorkflowFooterProps {
  existingWorkflow: boolean;
  hasSteps: boolean;
  onRunWorkflow: () => void;
  onCancel: () => void;
  onSave: () => void;
  isSaveDisabled: boolean;
  isCreating: boolean;
  modifierKeyName: "command" | "ctrl" | "shift" | "option" | "alt";
  buttonText: string;
  isPublic?: boolean;
  onPublishToggle?: () => void;
  onViewMarketplace?: () => void;
}

export default function WorkflowFooter({
  existingWorkflow,
  hasSteps,
  onRunWorkflow,
  onCancel,
  onSave,
  isSaveDisabled,
  isCreating,
  modifierKeyName,
  buttonText,
  isPublic,
  onPublishToggle,
  onViewMarketplace,
}: WorkflowFooterProps) {
  return (
    <div className="mt-8 border-t border-zinc-800 pt-6 pb-3">
      <div className="flex items-center justify-between">
        {/* Left side: Switch and Run Workflow */}
        <div className="flex items-center gap-4">
          {existingWorkflow && (
            <Tooltip
              content={
                !hasSteps
                  ? "Cannot run workflow without generated steps"
                  : "Manually run workflow"
              }
              placement="top"
            >
              <Button
                color="success"
                variant="flat"
                startContent={<PlayIcon className="h-4 w-4" />}
                onPress={onRunWorkflow}
                size="sm"
                isDisabled={!hasSteps}
              >
                Run
              </Button>
            </Tooltip>
          )}

          {existingWorkflow && !isPublic && onPublishToggle && (
            <Tooltip content="Share to community marketplace" placement="top">
              <Button
                variant="flat"
                size="sm"
                onPress={onPublishToggle}
                startContent={<GlobeIcon className="h-4 w-4" />}
              >
                Publish
              </Button>
            </Tooltip>
          )}

          {existingWorkflow && isPublic && onViewMarketplace && (
            <Tooltip content="Open community marketplace" placement="top">
              <Button
                variant="flat"
                size="sm"
                onPress={onViewMarketplace}
                startContent={<LinkSquare02Icon className="h-4 w-4" />}
              >
                View on Marketplace
              </Button>
            </Tooltip>
          )}
        </div>

        {/* Right side: Cancel and Save */}
        <div className="flex items-center gap-3">
          <Tooltip content={<Kbd keys={["escape"]} />} placement="top">
            <Button variant="flat" onPress={onCancel}>
              Cancel
            </Button>
          </Tooltip>
          <Tooltip
            content={<Kbd keys={[modifierKeyName, "enter"]} />}
            placement="top"
            isDisabled={isCreating || isSaveDisabled}
          >
            <Button
              color="primary"
              onPress={onSave}
              isLoading={isCreating}
              isDisabled={isSaveDisabled}
            >
              {buttonText}
            </Button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
