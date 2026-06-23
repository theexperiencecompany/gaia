import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Skeleton } from "@heroui/skeleton";
import {
  AlertCircleIcon,
  Minimize01Icon,
  PlusSignIcon,
  RedoIcon,
  ShuffleIcon,
  Wrench01Icon,
} from "@icons";
import { ChevronDown } from "@/components/shared/icons";
import type { Workflow } from "../../api/workflowApi";
import WorkflowSteps from "../shared/WorkflowSteps";
import PanelHeader from "./PanelHeader";

const DROPDOWN_ICON = "size-5 text-default-500 pointer-events-none shrink-0";

const regenerationReasons = [
  {
    key: "too_complex",
    label: "Too complex",
    description: "Simplify with fewer steps",
    icon: Minimize01Icon,
  },
  {
    key: "missing_functionality",
    label: "Missing functionality",
    description: "Add specific features",
    icon: PlusSignIcon,
  },
  {
    key: "wrong_tools",
    label: "Wrong tools",
    description: "Use different integrations",
    icon: Wrench01Icon,
  },
  {
    key: "alternative_approach",
    label: "Alternative approach",
    description: "Try a completely different strategy",
    icon: ShuffleIcon,
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
  isPreview?: boolean;
}

export default function WorkflowStepsPanel({
  workflow,
  isGenerating,
  isRegenerating,
  regenerationError,
  onRegenerateWithReason,
  onInitialGeneration,
  onClearError,
  isPreview = false,
}: WorkflowStepsPanelProps) {
  if (isPreview) {
    if (!workflow?.steps || workflow.steps.length === 0) {
      return (
        <div className="py-6 text-center text-sm text-zinc-500">
          Steps will be generated when this workflow runs.
        </div>
      );
    }
    return <WorkflowSteps steps={workflow.steps} />;
  }

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
        <Button variant="flat" size="sm" onPress={onClearError}>
          Try again
        </Button>
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
        <Button
          variant="flat"
          size="sm"
          color="primary"
          isLoading={isRegenerating}
          isDisabled={isRegenerating}
          startContent={!isRegenerating && <RedoIcon className="h-4 w-4" />}
          onPress={onInitialGeneration}
        >
          Generate steps
        </Button>
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
              variant="faded"
              onAction={(key) => onRegenerateWithReason(key as string)}
              disabledKeys={isRegenerating ? ["all"] : []}
            >
              {regenerationReasons.map((reason) => (
                <DropdownItem
                  key={reason.key}
                  textValue={reason.label}
                  description={reason.description}
                  startContent={<reason.icon className={DROPDOWN_ICON} />}
                >
                  {reason.label}
                </DropdownItem>
              ))}
            </DropdownMenu>
          </Dropdown>
        }
      />
      <div>
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
