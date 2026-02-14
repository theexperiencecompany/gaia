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
}: WorkflowRightPanelProps) {
  return (
    <div className="flex w-96 flex-col self-stretch rounded-2xl bg-zinc-950/30 p-3">
      <Tabs
        aria-label="Workflow info tabs"
        defaultSelectedKey="steps"
        fullWidth
      >
        <Tab
          key="steps"
          title={
            <div className="flex items-center gap-2">
              <span>Steps</span>
              {workflow?.steps?.length ? (
                <span className="rounded-full bg-primary/20 px-1.5 py-0.5 text-xs text-primary">
                  {workflow.steps.length}
                </span>
              ) : null}
            </div>
          }
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
