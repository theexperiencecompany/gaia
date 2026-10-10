import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";
import { PlayIcon, Share01Icon } from "@icons";

/** What the current edit session offers for auxiliary actions. */
interface WorkflowFooterWorkflow {
  /** An existing workflow is being edited (enables Run and Publish). */
  isExisting: boolean;
  /** Steps exist, so the workflow can be run right now. */
  hasSteps: boolean;
  /** Already published to the marketplace (hides Publish). */
  isPublic: boolean;
}

/** State of the primary save/create button. */
interface WorkflowFooterSave {
  isDisabled: boolean;
  isCreating: boolean;
  buttonText: string;
}

interface WorkflowFooterProps {
  workflow: WorkflowFooterWorkflow;
  save: WorkflowFooterSave;
  modifierKeyName: "command" | "ctrl" | "shift" | "option" | "alt";
  onRunWorkflow: () => void;
  onCancel: () => void;
  onSave: () => void;
  onPublish?: () => void;
}

export default function WorkflowFooter({
  workflow,
  save,
  modifierKeyName,
  onRunWorkflow,
  onCancel,
  onSave,
  onPublish,
}: WorkflowFooterProps) {
  const { isExisting, hasSteps, isPublic } = workflow;
  const { isDisabled, isCreating, buttonText } = save;

  return (
    <div className="flex items-center justify-between gap-3">
      {/* Left: run (edit only) */}
      <div className="flex items-center gap-2">
        {isExisting && (
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

        {isExisting && !isPublic && onPublish && (
          <Tooltip content="Share to the marketplace" placement="top">
            <Button
              variant="flat"
              startContent={<Share01Icon className="h-4 w-4" />}
              onPress={onPublish}
              className="active:scale-[0.97] transition-transform duration-150"
            >
              Publish
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
          isDisabled={isCreating || isDisabled}
        >
          <Button
            color="primary"
            onPress={onSave}
            isLoading={isCreating}
            isDisabled={isDisabled}
            className="active:scale-[0.97] transition-transform duration-150"
          >
            {buttonText}
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}
