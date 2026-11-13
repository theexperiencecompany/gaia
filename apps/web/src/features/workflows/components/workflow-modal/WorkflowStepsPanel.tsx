import { Dropdown, Skeleton } from "@heroui/react";
import { AlertCircleIcon, RedoIcon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { ChevronDown } from "@/components/shared/icons";
import type { Workflow } from "../../api/workflowApi";
import { REGENERATION_REASONS } from "../../constants/regeneration";
import WorkflowSteps from "../shared/WorkflowSteps";
import PanelHeader from "./PanelHeader";

const DROPDOWN_ICON = "size-5 text-zinc-400 pointer-events-none shrink-0";

interface WorkflowStepsPanelProps {
  workflow: Workflow | null;
  isGenerating: boolean;
  isRegenerating: boolean;
  regenerationError: string | null;
  onRegenerateWithReason: (reasonKey: string) => void;
  onInitialGeneration: () => void;
  onClearError: () => void;
}

export default function WorkflowStepsPanel({
  workflow,
  isGenerating,
  isRegenerating,
  regenerationError,
  onRegenerateWithReason,
  onInitialGeneration,
  onClearError,
}: WorkflowStepsPanelProps) {
  if (regenerationError) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
        <div className="rounded-full bg-danger/15 p-3">
          <AlertCircleIcon className="h-5 w-5 text-danger" />
        </div>
        <div>
          <p className="text-sm font-medium text-danger">Generation failed</p>
          <p className="mt-0.5 text-xs text-zinc-500">{regenerationError}</p>
        </div>
        <GaiaButton variant="default-soft" size="sm" onPress={onClearError}>
          Try again
        </GaiaButton>
      </div>
    );
  }

  if (!workflow?.steps || workflow.steps.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
        <div className="rounded-full bg-zinc-800/60 p-3">
          <RedoIcon className="h-5 w-5 text-zinc-500" />
        </div>
        <div>
          <p className="text-sm font-medium text-zinc-300">No steps yet</p>
          <p className="mt-0.5 text-xs text-zinc-500">
            Generate a plan for this workflow
          </p>
        </div>
        <GaiaButton
          variant="accent-soft"
          size="sm"
          isPending={isRegenerating}
          isDisabled={isRegenerating}
          onPress={onInitialGeneration}
        >
          {!isRegenerating && <RedoIcon className="h-4 w-4" />}
          Generate steps
        </GaiaButton>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <PanelHeader
        badge={`${workflow.steps.length} steps`}
        actions={
          <Dropdown>
            <GaiaButton
              variant="default-soft"
              size="sm"
              isPending={isRegenerating}
              isDisabled={isRegenerating}
            >
              {!isRegenerating && <RedoIcon className="h-4 w-4" />}
              {isRegenerating ? "Regenerating..." : "Regenerate"}
              {!isRegenerating && <ChevronDown className="h-4 w-4" />}
            </GaiaButton>
            <Dropdown.Popover placement="bottom end">
              <Dropdown.Menu
                aria-label="Regeneration reasons"
                onAction={(key) => onRegenerateWithReason(key as string)}
                disabledKeys={isRegenerating ? ["all"] : []}
              >
                {REGENERATION_REASONS.map((reason) => (
                  <Dropdown.Item
                    key={reason.key}
                    id={reason.key}
                    textValue={reason.label}
                  >
                    <reason.icon className={DROPDOWN_ICON} />
                    <div className="flex flex-col">
                      <span>{reason.label}</span>
                      <span className="text-xs text-muted">
                        {reason.description}
                      </span>
                    </div>
                  </Dropdown.Item>
                ))}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
        }
      />
      <div>
        {isRegenerating || isGenerating ? (
          <Skeleton className="h-32 w-full rounded-2xl" />
        ) : (
          <WorkflowSteps steps={workflow.steps || []} />
        )}
      </div>
    </div>
  );
}
