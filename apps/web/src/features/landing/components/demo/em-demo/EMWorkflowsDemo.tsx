import type { WorkflowStep } from "../WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../WorkflowsDemoBase";

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "wf-1",
    label: "Pulling sprint velocity",
    detail: "from Linear",
    category: "linear",
  },
  {
    id: "wf-2",
    label: "Calculating PR cycle times",
    detail: "from GitHub",
    category: "github",
  },
  {
    id: "wf-3",
    label: "Checking team blockers",
    detail: "from Slack",
    category: "slack",
  },
  {
    id: "wf-4",
    label: "Building retro document",
    detail: "in Notion",
    category: "notion",
  },
  {
    id: "wf-5",
    label: "Posting report to Slack",
    detail: "via #engineering",
    category: "slack",
  },
];

export default function EMWorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="Weekly Team Health Report"
      schedule="Every Friday at 5:00 PM"
      steps={WORKFLOW_STEPS}
    />
  );
}

export { EMWorkflowsDemo };
