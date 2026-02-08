import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Switch } from "@heroui/switch";
import { Tooltip } from "@heroui/tooltip";
import { PlayIcon } from "@/icons";

interface WorkflowFooterProps {
  mode: "create" | "edit";
  existingWorkflow: boolean;
  isActivated: boolean;
  isTogglingActivation: boolean;
  onToggleActivation: (activated: boolean) => void;
  hasSteps: boolean;
  onRunWorkflow: () => void;
  onCancel: () => void;
  onSave: () => void;
  isSaveDisabled: boolean;
  isCreating: boolean;
  modifierKeyName: "command" | "ctrl" | "shift" | "option" | "alt";
  buttonText: string;
}

export default function WorkflowFooter({
  mode,
  existingWorkflow,
  isActivated,
  isTogglingActivation,
  onToggleActivation,
  hasSteps,
  onRunWorkflow,
  onCancel,
  onSave,
  isSaveDisabled,
  isCreating,
  modifierKeyName,
  buttonText,
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
                Run Manually
              </Button>
            </Tooltip>
          )}

          {mode === "edit" && (
            <div className="flex items-center gap-3">
              <Tooltip
                content={
                  isActivated
                    ? "Deactivate this workflow to prevent it from running"
                    : "Activate this workflow to allow it to run"
                }
                placement="top"
              >
                <Switch
                  isSelected={isActivated}
                  onValueChange={onToggleActivation}
                  isDisabled={isTogglingActivation}
                  size="sm"
                />
              </Tooltip>
            </div>
          )}
        </div>

        {/* Right side: Cancel and Save */}
        <div className="flex items-center gap-3">
          <Button
            variant="flat"
            onPress={onCancel}
            endContent={<Kbd keys={["escape"]} />}
          >
            Cancel
          </Button>
          <Button
            color="primary"
            onPress={onSave}
            isLoading={isCreating}
            isDisabled={isSaveDisabled}
            endContent={
              !isCreating && <Kbd keys={[modifierKeyName, "enter"]} />
            }
          >
            {buttonText}
          </Button>
        </div>
      </div>
    </div>
  );
}
