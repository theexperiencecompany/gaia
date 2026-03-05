import type { WorkflowStep } from "../WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../WorkflowsDemoBase";

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "wf-1",
    label: "Pulling sprint metrics",
    detail: "from Linear",
    category: "linear",
  },
  {
    id: "wf-2",
    label: "Fetching release notes",
    detail: "from GitHub",
    category: "github",
  },
  {
    id: "wf-3",
    label: "Reading roadmap context",
    detail: "from Notion",
    category: "notion",
  },
  {
    id: "wf-4",
    label: "Drafting update email",
    detail: "3 recipients",
    category: "gmail",
  },
  {
    id: "wf-5",
    label: "Posting summary to Slack",
    detail: "via #product",
    category: "slack",
  },
];

export default function PMWorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="Weekly Stakeholder Update"
      schedule="Every Friday at 4:00 PM"
      steps={WORKFLOW_STEPS}
    />
  );
}

export { PMWorkflowsDemo };
