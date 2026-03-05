import type { WorkflowStep } from "../WorkflowsDemoBase";
import { WorkflowsDemoBase } from "../WorkflowsDemoBase";

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "wf-1",
    label: "Checking merged PRs",
    detail: "3 merged yesterday",
    category: "github",
  },
  {
    id: "wf-2",
    label: "Loading Linear tickets",
    detail: "5 completed",
    category: "linear",
  },
  {
    id: "wf-3",
    label: "Scanning Slack threads",
    detail: "12 unread",
    category: "slack",
  },
  {
    id: "wf-4",
    label: "Checking calendar",
    detail: "2 meetings today",
    category: "googlecalendar",
  },
  {
    id: "wf-5",
    label: "Posting standup",
    detail: "via Slack",
    category: "slack",
  },
];

export function SoftwareDevWorkflowsDemo() {
  return (
    <WorkflowsDemoBase
      title="Dev Daily Briefing"
      schedule="Every day at 9:00 AM"
      steps={WORKFLOW_STEPS}
    />
  );
}
