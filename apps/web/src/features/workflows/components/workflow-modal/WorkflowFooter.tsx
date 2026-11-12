import { Button, Kbd, Tooltip } from "@heroui/react";
import { PlayIcon, Share01Icon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";

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
          <Tooltip>
            <Button
              variant="secondary"
              onPress={onRunWorkflow}
              isDisabled={!hasSteps}
              className="active:scale-[0.97] transition-transform duration-150"
            >
              <PlayIcon className="h-4 w-4" />
              Run
            </Button>
            <Tooltip.Content placement="top">
              {!hasSteps
                ? "Generate steps before running"
                : "Run this workflow now"}
            </Tooltip.Content>
          </Tooltip>
        )}

        {isExisting && !isPublic && onPublish && (
          <Tooltip>
            <GaiaButton
              variant="default-soft"
              onPress={onPublish}
              className="active:scale-[0.97] transition-transform duration-150"
            >
              <Share01Icon className="h-4 w-4" />
              Publish
            </GaiaButton>
            <Tooltip.Content placement="top">
              Share to the marketplace
            </Tooltip.Content>
          </Tooltip>
        )}
      </div>

      {/* Right: cancel + primary save */}
      <div className="flex items-center gap-2">
        <Tooltip>
          <Button
            variant="ghost"
            onPress={onCancel}
            className="active:scale-[0.97] transition-transform duration-150"
          >
            Cancel
          </Button>
          <Tooltip.Content placement="top">
            <Kbd>
              <Kbd.Abbr keyValue="escape" />
            </Kbd>
          </Tooltip.Content>
        </Tooltip>
        <Tooltip isDisabled={isCreating || isDisabled}>
          <Button
            onPress={onSave}
            isPending={isCreating}
            isDisabled={isDisabled}
            className="active:scale-[0.97] transition-transform duration-150"
            variant="primary"
          >
            {buttonText}
          </Button>
          <Tooltip.Content placement="top">
            <Kbd>
              <Kbd.Abbr keyValue={modifierKeyName} />
              <Kbd.Abbr keyValue="enter" />
            </Kbd>
          </Tooltip.Content>
        </Tooltip>
      </div>
    </div>
  );
}
