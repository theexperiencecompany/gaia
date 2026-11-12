import { Tabs } from "@heroui/react";
import { Clock04Icon } from "@icons";
import { shapeVariants } from "@/components/shared/shape";
import { tabsVariants } from "@/components/shared/tabsVariants";
import type { Workflow } from "../../api/workflowApi";
import WorkflowExecutionHistory from "../WorkflowExecutionHistory";
import WorkflowStepsPanel from "./WorkflowStepsPanel";
import WorkflowStepsPreviewCard, {
  STEPS_CARD_SURFACE,
} from "./WorkflowStepsPreviewCard";

interface WorkflowRightPanelProps {
  workflow: Workflow | null;
  workflowId: string;
  isGenerating: boolean;
  isRegenerating: boolean;
  regenerationError: string | null;
  onRegenerateWithReason: (reasonKey: string) => void;
  onInitialGeneration: () => void;
  onClearError: () => void;
  isPreview?: boolean;
}

export default function WorkflowRightPanel({
  workflow,
  workflowId,
  isGenerating,
  isRegenerating,
  regenerationError,
  onRegenerateWithReason,
  onInitialGeneration,
  onClearError,
  isPreview = false,
}: WorkflowRightPanelProps) {
  if (isPreview) {
    return <WorkflowStepsPreviewCard steps={workflow?.steps ?? []} />;
  }

  return (
    <div className={STEPS_CARD_SURFACE}>
      <Tabs
        defaultSelectedKey="steps"
        className={tabsVariants({ color: "accent" }).base({
          className: shapeVariants({
            shape: "pill",
            className: "flex w-full shrink-0 flex-col",
          }),
        })}
      >
        <Tabs.List
          aria-label="Workflow info tabs"
          className="w-full overflow-x-hidden"
        >
          <Tabs.Tab id="steps" className="font-medium">
            Steps
            <Tabs.Indicator className="shadow-sm" />
          </Tabs.Tab>
          <Tabs.Tab id="history" className="font-medium">
            <div className="flex items-center gap-2">
              <Clock04Icon className="h-4 w-4" />
              <span>History</span>
            </div>
            <Tabs.Indicator className="shadow-sm" />
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel
          id="steps"
          className="scrollbar-hover min-h-0 flex-1 overflow-y-auto"
        >
          <WorkflowStepsPanel
            workflow={workflow}
            isGenerating={isGenerating}
            isRegenerating={isRegenerating}
            regenerationError={regenerationError}
            onRegenerateWithReason={onRegenerateWithReason}
            onInitialGeneration={onInitialGeneration}
            onClearError={onClearError}
          />
        </Tabs.Panel>
        <Tabs.Panel
          id="history"
          className="scrollbar-hover min-h-0 flex-1 overflow-y-auto"
        >
          <WorkflowExecutionHistory workflowId={workflowId} />
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
