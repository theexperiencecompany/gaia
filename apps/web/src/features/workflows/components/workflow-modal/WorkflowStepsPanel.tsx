import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Skeleton } from "@heroui/skeleton";
import { AlertCircleIcon, ChevronDown, RedoIcon } from "@/icons";
import type { Workflow } from "../../api/workflowApi";
import WorkflowSteps from "../shared/WorkflowSteps";
import PanelHeader from "./PanelHeader";

const regenerationReasons = [
  {
    key: "too_complex",
    label: "Too Complex",
    description: "Simplify with fewer steps",
  },
  {
    key: "missing_functionality",
    label: "Missing Functionality",
    description: "Add specific features",
  },
  {
    key: "wrong_tools",
    label: "Wrong Tools",
    description: "Use different integrations",
  },
  {
    key: "alternative_approach",
    label: "Alternative Approach",
    description: "Try a completely different strategy",
  },
] as const;

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
      <div className="space-y-4">
        <div className="flex flex-col items-center justify-center py-8">
          <div className="text-center">
            <div className="mb-4">
              <AlertCircleIcon className="mx-auto h-12 w-12 text-danger" />
            </div>
            <h3 className="text-lg font-medium text-danger">
              Generation Failed
            </h3>
            <p className="mb-4 text-sm text-zinc-400">{regenerationError}</p>
            <Button variant="flat" size="sm" onPress={onClearError}>
              Try Again
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (!workflow?.steps || workflow.steps.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="font-medium text-zinc-200">Workflow Steps</h4>
            <p className="text-xs text-zinc-500">No steps generated yet</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="flat"
              size="sm"
              color="primary"
              isLoading={isRegenerating}
              isDisabled={isRegenerating}
              startContent={<RedoIcon className="h-4 w-4" />}
              onPress={onInitialGeneration}
            >
              Generate Steps
            </Button>
          </div>
        </div>
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="mb-4 rounded-full bg-zinc-800/50 p-3">
            <RedoIcon className="h-6 w-6 text-zinc-500" />
          </div>
          <p className="text-sm text-zinc-400">
            Click "Generate Steps" to create your first workflow plan
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <PanelHeader
        badge={`${workflow.steps.length} steps`}
        actions={
          <Dropdown placement="bottom-end">
            <DropdownTrigger>
              <Button
                variant="flat"
                size="sm"
                color="primary"
                isLoading={isRegenerating}
                isDisabled={isRegenerating}
                endContent={
                  !isRegenerating && <ChevronDown className="h-4 w-4" />
                }
                startContent={
                  !isRegenerating && <RedoIcon className="h-4 w-4" />
                }
              >
                {isRegenerating ? "Regenerating..." : "Regenerate"}
              </Button>
            </DropdownTrigger>
            <DropdownMenu
              aria-label="Regeneration reasons"
              onAction={(key) => onRegenerateWithReason(key as string)}
              disabledKeys={isRegenerating ? ["all"] : []}
            >
              {regenerationReasons.map((reason) => (
                <DropdownItem
                  key={reason.key}
                  textValue={reason.label}
                  description={reason.description}
                >
                  {reason.label}
                </DropdownItem>
              ))}
            </DropdownMenu>
          </Dropdown>
        }
      />
      <div className="overflow-y-auto">
        <Skeleton
          className="rounded-2xl"
          isLoaded={!(isRegenerating || isGenerating)}
        >
          <WorkflowSteps steps={workflow.steps || []} />
        </Skeleton>
      </div>
    </div>
  );
}
