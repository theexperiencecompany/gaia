import type { WorkflowStep } from "../WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../WorkflowsDemoBase";

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "wf-1",
    label: "Pulling project progress",
    detail: "from ClickUp",
    category: "clickup",
  },
  {
    id: "wf-2",
    label: "Fetching metrics data",
    detail: "from Sheets",
    category: "googlesheets",
  },
  {
    id: "wf-3",
    label: "Checking open items",
    detail: "from email",
    category: "gmail",
  },
  {
    id: "wf-4",
    label: "Drafting status report",
    detail: "8 clients",
    category: "gmail",
  },
  {
    id: "wf-5",
    label: "Notifying account team",
    detail: "via Slack",
    category: "slack",
  },
];

function agencyFallbackIcon() {
  return (
    <div className="h-[22px] w-[22px] rounded-full bg-purple-400/30 flex items-center justify-center">
      <div className="h-2 w-2 rounded-full bg-purple-400" />
    </div>
  );
}

export function AgencyWorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="Weekly Client Report — TechCorp"
      schedule="Every Friday at 4:00 PM"
      steps={WORKFLOW_STEPS}
      fallbackIcon={agencyFallbackIcon}
    />
  );
}
