import { Tab, Tabs } from "@heroui/tabs";
import { Clock04Icon } from "@icons";

import type { Workflow } from "../../api/workflowApi";
import WorkflowExecutionHistory from "../WorkflowExecutionHistory";
import WorkflowStepsPanel from "./WorkflowStepsPanel";

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

const PANEL_SURFACE =
  "flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl bg-zinc-800/50 p-4";

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
    return (
      <div className={PANEL_SURFACE}>
        <div className="mb-1 flex items-center gap-2 px-2 pt-1">
          <span className="text-sm font-medium text-zinc-200">Steps</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          <WorkflowStepsPanel
            workflow={workflow}
            isGenerating={isGenerating}
            isRegenerating={isRegenerating}
            regenerationError={regenerationError}
            onRegenerateWithReason={onRegenerateWithReason}
            onInitialGeneration={onInitialGeneration}
            onClearError={onClearError}
            isPreview
          />
        </div>
      </div>
    );
  }

  return (
    <div className={PANEL_SURFACE}>
      <Tabs
        aria-label="Workflow info tabs"
        defaultSelectedKey="steps"
        fullWidth
        color="primary"
        radius="full"
        classNames={{
          // base wraps only the tab list — keep it shrink-0 so the panel
          // (its flex-1 sibling) fills the remaining surface height and scrolls
          // internally. Putting h-full here collapses the panel to its padding.
          base: "w-full shrink-0",
          // HeroUI's tabList defaults to overflow-x-scroll, which paints a
          // permanent scrollbar track even though fullWidth tabs always fit.
          tabList: "w-full overflow-x-hidden bg-zinc-800/80 p-1",
          cursor: "shadow-sm",
          tabContent:
            "font-medium text-zinc-400 group-data-[selected=true]:text-black",
          panel: "min-h-0 flex-1 overflow-y-auto px-1 py-2",
        }}
      >
        <Tab key="steps" title="Steps">
          <WorkflowStepsPanel
            workflow={workflow}
            isGenerating={isGenerating}
            isRegenerating={isRegenerating}
            regenerationError={regenerationError}
            onRegenerateWithReason={onRegenerateWithReason}
            onInitialGeneration={onInitialGeneration}
            onClearError={onClearError}
          />
        </Tab>
        <Tab
          key="history"
          title={
            <div className="flex items-center gap-2">
              <Clock04Icon className="h-4 w-4" />
              <span>History</span>
            </div>
          }
        >
          <WorkflowExecutionHistory workflowId={workflowId} />
        </Tab>
      </Tabs>
    </div>
  );
}
