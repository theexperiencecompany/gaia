import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import { PlayIcon } from "@icons";

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
}: WorkflowFooterProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      {/* Left: run (edit only) */}
      <div className="flex items-center gap-2">
        {existingWorkflow && (
          <Tooltip
            content={
              !hasSteps
                ? "Generate steps before running"
                : "Run this workflow now"
            }
            placement="top"
          >
            <Button
              color="success"
              variant="flat"
              startContent={<PlayIcon className="h-4 w-4" />}
              onPress={onRunWorkflow}
              isDisabled={!hasSteps}
              className="active:scale-[0.97] transition-transform duration-150"
            >
              Run
            </Button>
          </Tooltip>
        )}
      </div>

      {/* Right: cancel + primary save */}
      <div className="flex items-center gap-2">
        <Tooltip content={<Kbd keys={["escape"]} />} placement="top">
          <Button
            variant="light"
            onPress={onCancel}
            className="active:scale-[0.97] transition-transform duration-150"
          >
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
            className="active:scale-[0.97] transition-transform duration-150"
          >
            {buttonText}
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}
